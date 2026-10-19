# Technology and Information Systems

## Core Data Domains

Sampurna's operating model separates product catalog, inventory, pricing, buyer master, historical transactions, and knowledge documents. Each domain has a different update pattern and source of truth.

## Product Catalog

The product catalog holds stable SKU attributes. Downstream files and databases refer to products using SKU rather than free-text name.

## Inventory

Inventory changes frequently and is stored by warehouse and SKU. It requires structured queries for current availability.

## Pricing

Pricing is effective-dated and conditioned by buyer type, tier, and quantity. A search result that ignores dates or slabs can return the wrong price.

## Buyer Master

The buyer master contains identity, type, contact, tier, credit, payment, discount group, and status fields. Access to account-specific data requires authorization.

## Transactions

Historical orders use one row per line item. Order-level fields repeat across lines so the CSV can later be normalized into order headers and items. Historical prices and taxes remain unchanged when current master data changes.

## Knowledge Retrieval

Markdown knowledge is appropriate for policies, procedures, definitions, regions, contacts, and explanatory content. It should not be treated as the live store for quantities, balances, or current prices.

## Data Quality Controls

- Stable and unique identifiers
- Valid foreign-key relationships
- Non-negative quantities
- Available stock reconciled to on-hand less reserved
- Valid price dates and non-overlapping conditions where required
- Shipment and delivery dates in chronological order
- Monetary arithmetic reconciliation
- Controlled categorical values

## Change Management

Corrections should preserve an audit trail. A current master correction should not silently rewrite historical transactions unless a formal restatement process applies.

