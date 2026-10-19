# Data and Assistant Behaviour FAQs

## Which questions should use SQL or structured tools?

Use structured data for current stock, prices, buyer tiers, credit limits, order history, payment status, and shipment events. These facts change and require exact filtering or joins.

## Which questions should use this knowledge base?

Use retrieval for policies, procedures, service explanations, region rules, handling guidance, escalation contacts, and FAQs.

## Can the knowledge base answer current inventory?

No. It can explain how availability works but cannot provide the latest quantity.

## Can historical unit price be replaced with today's price?

No. Historical transactions must retain the price used at the time.

## What should happen when two sources conflict?

Prefer the authoritative source for the field, consider effective dates and last-updated timestamps, and disclose the conflict rather than inventing a resolution.

## Should missing maximum quantity be treated as zero?

No. In pricing data, a blank maximum can mean no upper bound. The data contract must define this interpretation.

## Can a language model infer buyer tier from order size?

No. Tier comes from the buyer master. Large orders do not automatically make a buyer Gold.

## Is vector similarity an access-control mechanism?

No. Account-specific retrieval must verify authorization before exposing buyer data.

## How should ambiguous products be handled?

Return candidate SKUs with identifying details and request selection. Do not guess a pack size or variant.

## What should an answer say about estimates?

Clearly label replenishment, dispatch, and delivery dates as estimates unless a confirmed event is available.

