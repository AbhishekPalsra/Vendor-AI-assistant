# Product Catalog Identification Guide

## Why Exact Identification Matters

Product name, brand, pack size, and unit type work together to define a sellable item, but SKU is the stable key used for inventory, pricing, orders, and claims. Similar descriptions must not be treated as the same item.

## Required Fields

- SKU
- Product name
- Category
- Brand
- Pack size
- Unit type

## Common Ambiguities

### Similar Product Names

A brand may sell several variants with similar names. Use the complete product name and SKU.

### Different Pack Sizes

A 500 g, 1 kg, and 5 kg version are separate SKUs. Inventory for one size cannot fulfil another without an approved substitution.

### Units of Measure

`g` and `kg`, or `ml` and `L`, must not be compared without conversion. `pack` describes a packaged configuration and cannot be converted to weight or volume unless product master data explicitly supplies the conversion.

### Brand Versus Manufacturer

The catalog records brand. Manufacturer or legal-marketer information should be taken from the product label or a separate approved master, not inferred from brand name.

## Search Guidance

When the user supplies an incomplete name, return a short candidate list with SKU, full product name, brand, category, pack size, and unit type. Ask for selection before placing or changing an order.

## Corrections

A suspected catalog error should be reported with SKU, current value, expected value, source evidence, and date. Do not silently change downstream transaction history. Historical records should retain the description and price used at the time or remain linked to the stable SKU.

## RAG Boundary

This guide explains how to interpret the catalog. It does not contain current availability or prices. Those require structured inventory and pricing queries.

