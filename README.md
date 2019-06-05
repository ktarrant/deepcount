# deepcount
Constraining the problem of predicting price

# The Agent

Consider an agent that is a participant in a market. Allow us to make the following constraints/assumptions:
1. The agent starts in a market that is open.
2. The agent starts without an open position or order.
3. The market does not close while the agent is running.
4. There can be only one pending order open at a time.
5. The agent can trade just one unit of the financial product at a time. (i.e. The agent's pending order is always one of {+1, 0, -1})
6. The agent can't add to the position. (i.e. The agent's position is always one of {-1, 0, 1}).

From these assumptions we can deduce:
- If the agent's position is non-0 (i.e. the "protect" case), the pending order must be either 0 or opposite sign to the position (i.e. a "closing" order).
- Therefore there are 7 possible combinations of (position, pending) conditions which map to the current state of the agent.
