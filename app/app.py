# HTTP SERVER

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import ForeignKey, inspect
from simulator import Simulator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from store import QRangeStore
import logging
from datetime import datetime, UTC

class Base(DeclarativeBase):
    pass


############################## Application Configuration ##############################

app = Flask(__name__)
CORS(app, origins=["http://localhost:3030"])

db = SQLAlchemy(model_class=Base)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
db.init_app(app)

# logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=logging.DEBUG)

############################## Database Models ##############################


class Simulation(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[int] = mapped_column(default=0)
    iterations: Mapped[int] = mapped_column(default=500)  # default to 500 timesteps
    timestep: Mapped[float] = mapped_column(default=0.01)  # default to 0.01 timestep
    num_agents: Mapped[int] = mapped_column(default=0)  # default to 0 agents
    
class AgentState(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    # FK reference to simulation table which holds sim run records
    sim_id: Mapped[int] = mapped_column(ForeignKey("simulation.id"), index=True)
    agent_id: Mapped[str] = mapped_column(default="Body1")
    t_start: Mapped[int] = mapped_column(default=0, index=True)  # default to 0
    t_end: Mapped[int] = mapped_column(default=0)  # default to 0
    vel_x: Mapped[float] = mapped_column(default=0.0)  # default to 0.0
    vel_y: Mapped[float] = mapped_column(default=0.0)
    vel_z: Mapped[float] = mapped_column(default=0.0)
    position_x: Mapped[float] = mapped_column(default=0.0)
    position_y: Mapped[float] = mapped_column(default=0.0)
    position_z: Mapped[float] = mapped_column(default=0.0)
    mass: Mapped[float] = mapped_column(default=0.0)


with app.app_context():
    db.create_all()


############################## API Endpoints ##############################


@app.get("/")
def health():
    return "<p>Sedaro Nano API - running!</p>"

def combine_agent_states(agent_states: list[AgentState]) -> tuple[int, int, dict]:
    """Combine a list of AgentState objects into a single dictionary keyed by agent_id."""
    combined_states = {}
    for state in agent_states:
        combined_states[state.agent_id] = {
            "velocity": {
                "x": state.vel_x,
                "y": state.vel_y,
                "z": state.vel_z,
            },
            "position": {
                "x": state.position_x,
                "y": state.position_y,
                "z": state.position_z,
            },
            "mass": state.mass,
        }
    return agent_states[0].t_start, agent_states[0].t_end, combined_states

def rebuild_data(agent_states: list[AgentState]) -> list[tuple[int, int, dict]]:
    # Rebuild the agent state data into the [t_start, t_end, {agent_states}] format
    # that the front end expects so that we don't have to update the front end code to 
    # handle the new database schema.
    
    # Initial DataPoint should contain all agent states. Check for t_start < 0
    initial_state: tuple[int, int, dict] = None
    if agent_states and agent_states[0].t_start < 0:
        logging.debug(f"Initial agent state has t_start < 0, combining agent states with t_start < 0 into a single initial state.")
        initial_state = combine_agent_states([state for state in agent_states if state.t_start < 0])

    rebuilt_data = []
    for state in agent_states:
        if state.t_start < 0:
            continue  # skip initial state, already handled above
        rebuilt_data.append((state.t_start, state.t_end, {
            state.agent_id: {
                "velocity": {
                    "x": state.vel_x,
                    "y": state.vel_y,
                    "z": state.vel_z,
                },
                "position": {
                    "x": state.position_x,
                    "y": state.position_y,
                    "z": state.position_z,
                },
                "mass": state.mass,
            }
        }))
    # Restructured data in the form [(t_start, t_end, data dict)]
    rebuilt_data = [initial_state] + rebuilt_data if initial_state else rebuilt_data
    return rebuilt_data

@app.get("/simulation")
def get_data():
    # Get most recent simulation from database
    simulation: Simulation = Simulation.query.order_by(Simulation.id.desc()).first()
    if simulation is None:
        logging.info("No simulation found in database.")
        return []
    logging.debug(f"Getting most recent simulation from database: {simulation.id}")
    agent_states: list[AgentState] = AgentState.query.filter_by(sim_id=simulation.id).order_by(AgentState.t_start).all() if simulation else None
    rebuilt_data = rebuild_data(agent_states) if agent_states else []
    logging.debug(f"Number of of agent states: {len(rebuilt_data)}")
    json_output = jsonify(rebuilt_data)
    # Add number of iterations to header
    headers = {
        "Sim-Iterations": str(simulation.iterations),
        "Access-Control-Expose-Headers": "Sim-Iterations"
    }
    return json_output, 200, headers

def flatten_agent_state_data(sim_id: int, data: tuple) -> list[dict]:
    """Flatten the data from the QRangeStore into a list of dicts with keys
     matching the schema column names so that bulk_insert_mappings()
    can be used to update AgentState table."""
    t_start, t_end = data[0], data[1]
    agent_states = []
    for agent_id, agent_data in data[2].items():
        agent_states.append({
            "sim_id": sim_id,
            "t_start": t_start,
            "t_end": t_end,
            "agent_id": agent_id,
            "vel_x": agent_data.get("velocity", {}).get("x", 0.0),
            "vel_y": agent_data.get("velocity", {}).get("y", 0.0),
            "vel_z": agent_data.get("velocity", {}).get("z", 0.0),
            "position_x": agent_data.get("position", {}).get("x", 0.0),
            "position_y": agent_data.get("position", {}).get("y", 0.0),
            "position_z": agent_data.get("position", {}).get("z", 0.0),
            "mass": agent_data.get("mass", 0.0),
        })
    return agent_states

@app.post("/simulation")
def simulate():
    # Get data from request in this form
    # init = {
    #     "Body1": {"x": 0, "y": 0.1, "vx": 0.1, "vy": 0},
    #     "Body2": {"x": 0, "y": 1, "vx": 1, "vy": 0},
    # }

    # Define time and timeStep for each agent
    init: dict = request.json
    logging.info(f"Received simulation request with initial state: {init}")
    # Extract sim configs
    config = init.pop("Config", {}) # pop config to avoid passing as an agent to the simulator
    logging.debug(f"Simulating for agents: {init.keys()} with config: {config}")
    for key in init.keys():
        init[key]["time"] = 0
        init[key]["timeStep"] = config.get("timestep", 0.01)

    # Create store and simulator
    t = datetime.now()
    store = QRangeStore()
    simulator = Simulator(store=store, init=init)
    logging.info(f"Time to Build: {datetime.now() - t}")

    # Run simulation
    t = datetime.now()
    # Override default num iterations with user input
    simulator.simulate(iterations=config.get("numIterations", 500))
    logging.info(f"Time to Simulate: {datetime.now() - t}")

    # Save data to database
    # 2 tables: Simulation (sim config/metadata) and AgentState (single agent's state data per timestep)
    simulation = Simulation(created_at=0, 
                            iterations=config.get("numIterations", 500),
                            timestep=config.get("timestep", 0.01),
                            num_agents=len(init))
    
    db.session.add(simulation)
    db.session.flush()  # flush to get the simulation id for the agent states
    flattened_data = []
    for data in store.store:
        flattened_data.extend(flatten_agent_state_data(simulation.id, data))
    
    logging.debug(f"Flattened agent states data[0] for bulk insert: {flattened_data[0]}")
    db.session.bulk_insert_mappings(AgentState, flattened_data)
    db.session.commit()

    return store.store
