Albert Ki
11/17/2026

## Writeup for Sedaro Nano Project

For the Sedaro nano project I decided to focus on 2 linked improvements: 
making the simulation length configurable, and replacing the single 
JSON-string storage with a proper schema for both simulation config data
and agent states.

### Configurable simulation duration

I added a user-configurable number of iterations to the form, defaulting 
to 500. The setting is stored separately as 
`Config: { numIterations: 500 }`, and the backend extracts it before the 
agent loop so it isn't mistaken for a third body, then passes it to the 
simulator.

### Database storage into Simulation and AgentState tables

Split simulation datastorage into two tables. Simulation holds one row per
run with the run metadata, and AgentState holds one row per agent per timestep, 
with position, velocity, mass, time, and time step as separate columns, 
linked by simulation id.

/POST endpoint now creates the Simulation row first, then flattens the
simulator output and bulk-inserts the rows into AgentState.
/GET endpoint queries and rebuilds JSON sequence of agent states using
the latest simulation's sim id.

Prior to this refactoring, longer runs meant loading and parsing an 
ever-growing JSON string into memory. The AgentState table allows you
to query just the slice you need, which enables UI features like a 
time-range filter, playback by agent field, or even overlaying agent 
states from different simulations, without loading the full run. Also 
adds schema validation, hence, a missing required field in AgentState 
fails the insert instead of being silently saved in the JSON
blob.

### Tradeoffs and scope

The tradeoff is flexibility. Normalized columns obviously assume agents 
share the same fields, so an agent with different fields would require 
a migration, whereas the preexisting JSON string would accept anything
at the database level.

I kept this refactor as transparent as possible to the frontend to minimize 
changes to the form and display files. (Given the 6-hour limit, I wanted to 
contain the scope to these two backend-focused changes, rather than 
potentially adding more front-end work with React.)

### Tools used

Browser console for front end debugging, and sqlite3 was added to the 
Dockerfile to verify data as it was saved to the database. VS Code Github 
Copilot extension was used only for coding assist/autofill, not or concrete 
implementations or solutions. Muse was used for a draft of the writeup to 
summarize my bullet points. Google search AI overview was used to understand 
basic usage of React hooks usage in the Typescript files.

