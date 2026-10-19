# Inventory Availability Rules

## Availability Calculation

Available quantity is calculated as:

`available quantity = quantity on hand - reserved quantity`

The result should never be negative. If source data produces a negative result, the record requires investigation and should not be used for a promise.

## Location Matters

Availability is stored by SKU and warehouse. A product may be available in Mumbai but unavailable in Jaipur. A company-wide total is insufficient when the buyer asks whether the product can be delivered to a particular location.

## Reservation Rules

Reserved quantity represents units committed to existing demand. The units may still be visible in the building, but they cannot be sold again. Reservations are released by cancellation, expiry of a valid reservation, or an authorized order adjustment.

## Reorder Level

Reorder level is a planning threshold, not an automatic out-of-stock point. Stock below reorder level can still be available, but replenishment attention is required. A low-stock warning must not be presented as a confirmed inbound delivery date.

## Stale Records

The last-updated timestamp indicates record freshness. For a high-volume or urgent order, a stale record may require a live warehouse confirmation. The acceptable freshness threshold depends on operational risk.

## Transfers and Inbound Goods

- Stock at the source remains source stock until transfer dispatch is posted.
- In-transit stock is not destination availability.
- Destination stock becomes available only after receiving and quality checks.
- Quarantined or damaged goods are not available stock.

## Availability Responses

A useful answer should include SKU, product name, warehouse or service location, available quantity, and timestamp. For a retailer quote, it should also retrieve the correct tier price using requested quantity.

## Prohibited Assumptions

- Do not treat on-hand quantity as available quantity.
- Do not combine incompatible pack sizes as the same SKU.
- Do not promise replenishment based only on reorder level.
- Do not use historical order quantities as current inventory.

