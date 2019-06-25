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

If we were to sample the status of the agent at regular intervals, a market buy followed by a limit sell might look something like this:

index    | 0 | 1 | 2 | 3  | 4 | 5
---------|---|---|---|----|---|--
pending  | 0 | 0 | 0 | -1 | 0 | 0
position | 0 | 1 | 1 | 1  | 0 | 0

Note that we can expect the market buy to execute immediately, so the pending never goes to 1. Whereas the limit sell doesn't execute immediately, so one sample shows a pending -1 with the position still at 1.

If we only use market orders then we can eliminate the "pending" steps entirely, reducing the number of possible agent states to just the three position states.


index    | 0 | 1 | 2 | 3  | 4  | 5
---------|---|---|---|----|----|--
position | 0 | 1 | 0 | -1 | -1 | 0

# Price

Open-High-Low-Close (OHLC) candlestick data is the primary input the system will have to make decisions. Historical OHLC data, with a variety of bar sizes (i.e. time resolutions), are available through brokers and data services. There is a vast universe of patterns and indicators based on OHLC data that summarize support and resistance levels. There are a number of trading systems that are based on OHLC data alone, although more often they are used in conjugtion with other types of data to create a complete system.

Index    | 0  | 1  | 2  | 3  | 4  | 5
---------|----|----|----|----|----|---
Open     | 10 |  8 | 12 | 17 | 16 | 15
High     | 15 | 20 | 21 | 18 | 17 | 20
Low      | 8  | 10 | 12 | 10 | 13 | 15
Close    | 12 | 14 | 17 | 17 | 15 | 19

## TD Count

Tom Demark Sequential Count is somewhat well-known indicator that can be quickly deployed as a simple trading system. The underlying method for determining "direction" of the count is to compare the most recent bar to the bar 4 periods previous. The count is then the number of consecutive bars which have had the same direction. Typically, the indicator is used to guess tops/bottoms in price by signaling sell/buy after a large count is reversed.

Index    | 0  | 1  | 2  | 3  | 4  | 5  | 6  | 7  | 8  | 9  | 10 | 11
---------|----|----|----|----|----|----|----|----|----|----|----|----
Close    | 12 | 14 | 17 | 17 | 15 | 19 | 18 | 16 | 14 | 19 | 17 | 15
TDD      | na | na | na | na | +1 | +1 | +1 | -1 | -1 | 0  | -1 | -1
TDC      | 0  | 0  | 0  | 0  | 1  | 2  | 3  | -1 | -2 | 0  | -1 | -2

