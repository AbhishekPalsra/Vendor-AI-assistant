# Company Overview

## Overview

Sampurna Wholesale Distribution Pvt. Ltd. is a synthetic fast-moving consumer goods distributor serving retailers and direct customers in selected Indian cities. The company coordinates product information, regional inventory, account-specific pricing, credit terms, order fulfilment, shipment tracking, delivery support, and after-sales claims through a common operating model.

The organization is designed around a six-warehouse network. Delhi NCR acts as the primary coordination hub, supported by warehouses in Jaipur, Mumbai, Bengaluru, Kolkata, and Lucknow. Each hub maintains inventory by SKU and serves a defined mix of local, regional, and inter-region routes.

## Customer Segments

### Direct Customers

Direct customers use IDs beginning with `CUS-`. They normally purchase in small quantities at the standard customer price. Payment is generally prepaid or due on receipt. Direct customers do not receive a retailer tier or an account credit limit.

### Retailers

Retailers use IDs beginning with `RET-`. Approved retailer accounts receive Bronze, Silver, or Gold pricing. The applicable unit price depends on the SKU, order quantity, retailer tier, and pricing validity dates. Credit terms and credit limits are stored on the account and may be changed after financial review.

## Product and Inventory Model

The catalog contains packaged FMCG products identified by stable SKU codes. Product details include product name, category, brand, pack size, and unit type. Inventory is not stored as one company-wide total. It is recorded separately for each SKU and warehouse.

Three inventory quantities have distinct meanings:

- **Quantity on hand:** Physical units recorded at a warehouse
- **Reserved quantity:** Units committed to confirmed or allocated orders
- **Available quantity:** Quantity on hand minus reserved quantity

A product can be listed in the catalog but unavailable in a specific location. Availability answers must therefore use both the catalog and warehouse inventory.

## Pricing Model

Customer and retailer pricing are represented as dated price records. Each record identifies the SKU, buyer type, retailer tier where applicable, minimum and maximum quantities, base price, discount percentage, net unit price, and validity dates.

Retailer slabs apply per order line and per SKU. Quantities from different SKUs do not combine. When an order line crosses a slab boundary, the entire line is repriced using the applicable valid record unless a written contract specifies another method.

## Order Lifecycle

An order typically moves through Pending Confirmation, Confirmed, Allocated, Picked, Packed, Shipped, and Delivered. Cancelled and Returned are terminal exception states. Payment status is tracked separately because a delivered retailer order can remain unpaid during its approved credit period.

## Quality Commitment

Sampurna aims to maintain traceable batches, appropriate storage, accurate picking, secure packaging, and prompt claim handling. Product labels and manufacturer instructions always take priority over general knowledge-base guidance.

