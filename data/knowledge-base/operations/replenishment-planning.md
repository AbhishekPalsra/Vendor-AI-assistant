# Replenishment Planning

## Purpose

Replenishment maintains sufficient warehouse stock while controlling excess, expiry, and transfer cost. It combines current inventory, reorder levels, demand history, confirmed orders, inbound supply, lead time, and promotional plans.

## Reorder Signals

Available quantity at or below reorder level is a planning signal. It is not automatically a purchase order, stockout, or confirmed replenishment date.

## Planning Inputs

- On-hand, reserved, and available quantity
- Reorder level
- Recent and seasonal sales history
- Open confirmed orders
- Supplier and transfer lead times
- Minimum purchase quantities
- Remaining shelf life and batch risk
- Promotions, holidays, and regional events
- Warehouse capacity

## Replenishment Options

### Supplier Purchase

Used when approved supply and lead time meet the need. Inbound quantity remains unavailable until receipt and inspection.

### Inter-Warehouse Transfer

Used when another hub has suitable excess. Planners consider source demand, freight, transit time, batch shelf life, and destination capacity.

### Allocation Control

During shortage, planners may restrict large orders or protect stock for confirmed commitments. Restrictions require clear scope and review.

## Short-Dated Risk

Ordering too much can create expiry risk. Forecasts should consider pack size, category velocity, regional demand, and current batch dates.

## Communication

Support may communicate an approved replenishment estimate but must label it as estimated. Only received and posted stock can be quoted as current availability.

## Performance Measures

Useful measures include stockout rate, fill rate, days of supply, aged stock, expiry loss, transfer frequency, supplier lead-time accuracy, and forecast error.

