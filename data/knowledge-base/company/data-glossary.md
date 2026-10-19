# Business Data Glossary

## Product Terms

- **SKU:** Stable stock-keeping identifier such as `SKU-00001`.
- **Product Name:** Human-readable brand, item, and pack description.
- **Category:** Commercial grouping used for search, reporting, handling, and tax logic.
- **Pack Size:** Numeric amount contained in one sellable unit.
- **Unit Type:** Measurement associated with pack size, such as g, kg, ml, L, or pack.

## Inventory Terms

- **Warehouse ID:** Identifier for a physical fulfilment hub.
- **Quantity on Hand:** Physical stock recorded at the warehouse.
- **Reserved Quantity:** Stock already committed to orders.
- **Available Quantity:** On-hand quantity less reserved quantity; it cannot be negative.
- **Reorder Level:** Planning threshold that signals replenishment may be required.
- **Last Updated:** Timestamp of the latest inventory record update.

## Buyer Terms

- **Buyer ID:** Customer or retailer identifier used on orders.
- **Buyer Type:** `Customer` or `Retailer`.
- **Retailer Tier:** Bronze, Silver, Gold, or Not Applicable for direct customers.
- **Discount Group:** Account code used to connect a buyer to commercial rules.
- **Credit Limit:** Maximum approved credit exposure, subject to available credit.
- **Payment Terms:** Due-date rule such as Due on Receipt, Prepaid, Net 15, Net 30, or Net 45.

## Pricing Terms

- **Base Price:** Standard pre-discount unit price for the pricing period.
- **Minimum Quantity:** Lowest quantity eligible for the price row.
- **Maximum Quantity:** Highest eligible quantity; blank can mean no upper limit.
- **Discount Percentage:** Reduction applied to the base price.
- **Net Unit Price:** Base price after the row's discount.
- **Validity Dates:** Inclusive period during which a pricing row may be used.

## Order Terms

- **Order ID:** Identifier shared by every line item in the same order.
- **Line Item Number:** Sequence number within an order.
- **Historical Unit Price:** Unit price actually used at the time of the transaction.
- **Gross Amount:** Quantity multiplied by historical unit price.
- **Discount Amount:** Monetary reduction from gross amount.
- **Taxable Amount:** Gross amount less discount amount.
- **Tax Amount:** Taxable amount multiplied by the applicable tax rate.
- **Line Total:** Taxable amount plus tax amount.

## Status Terms

- **Order Status:** Operational state of fulfilment.
- **Payment Status:** Financial state, tracked separately from fulfilment.
- **Shipment Date:** Date goods were handed to the carrier.
- **Expected Delivery Date:** Estimated date, not a guaranteed completion date.
- **Delivery Date:** Date recorded as delivered.
- **Returned:** Goods were delivered and later entered a return process.
- **Cancelled:** Order stopped before successful fulfilment.

