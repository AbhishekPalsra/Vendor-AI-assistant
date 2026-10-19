# Customer and Retailer Service Model

## Purpose

This document explains how Sampurna handles questions and service requests from direct customers and retailers. It is intended to help support staff and automated assistants choose the correct source of truth.

## Information Sources

Different questions require different data sources:

- Product identity, brand, category, and pack details come from the product catalog.
- Current stock comes from warehouse inventory, not policy documents.
- Applicable prices come from dated pricing records and the buyer account.
- Credit limits, payment terms, tiers, and discount groups come from the buyer master.
- Historical purchases, prices, taxes, and delivery events come from transaction history.
- Policies, procedures, regions, and handling guidance come from this knowledge base.

Policy text must not be used as a substitute for live operational quantities or prices.

## Common Service Journeys

### Product Availability Request

Collect the product or category, delivery location, buyer type, and buyer ID when available. Match the location to eligible warehouses, then return only SKUs with positive available quantity. For a retailer, retrieve the retailer tier before selecting a price.

### Price Request

Collect SKU, buyer ID or buyer type, requested quantity, and effective date. Select a pricing record whose validity dates include the effective date and whose quantity range contains the requested quantity. Do not assume every retailer is Bronze.

### Order Status Request

Use the order ID to retrieve the order state, payment state, shipment record, carrier, and tracking number. Do not infer delivery from payment or payment from delivery.

### Return or Damage Request

Collect order ID, SKU, affected quantity, delivery date, reason, photographs when applicable, batch information, and packaging condition. Compare the request date with the correct claim window.

### Credit or Payment Request

Use the retailer account record and open financial records. General tier limits are examples, while the account-specific limit is authoritative.

## Escalation Principles

Escalate when information conflicts, a safety concern is reported, a batch may affect multiple buyers, a legal or tax interpretation is requested, or an exception outside published policy is needed.

## Communication Standards

- State what is confirmed and what remains estimated.
- Use exact order IDs, buyer IDs, SKUs, dates, quantities, and currency values.
- Avoid promising stock until reservation or order confirmation is complete.
- Avoid promising a refund until the claim is approved.
- Never expose another buyer's pricing, credit, contacts, or transaction history.

