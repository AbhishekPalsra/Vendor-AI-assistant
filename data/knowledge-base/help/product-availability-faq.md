# Product Availability FAQs

## What information is needed for an availability search?

Provide a product name, category, brand, or SKU; delivery city or postal code; and buyer type. For retailer pricing, also provide retailer ID and requested quantity.

## Why are products available in one city but not another?

Inventory is stored by SKU and warehouse. Different hubs hold different quantities and reservations. Location determines which warehouses and routes are suitable.

## What does available quantity mean?

Available quantity is quantity on hand minus reserved quantity. On-hand stock already promised to another order is not available.

## Can stock below reorder level still be ordered?

Possibly. Reorder level is a planning threshold. Positive available stock may still be sold unless a planner has placed a restriction.

## Does an inbound transfer count as available?

No. The destination can treat it as available only after receipt, inspection, and posting.

## Can another pack size be supplied instead?

Only with buyer approval. Different pack sizes have different SKUs, prices, taxes, and quantities.

## Can support reserve stock during an enquiry?

An enquiry does not reserve stock. Reservation occurs only through the approved order workflow.

## How fresh should inventory data be?

Use the last-updated timestamp. Large or urgent orders may require warehouse confirmation when the record is stale or stock is moving quickly.

## Can historical sales predict current stock?

Historical data can support forecasting, but it cannot prove current availability. Use the inventory table for current stock.

