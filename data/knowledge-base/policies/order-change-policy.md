# Order Change Policy

## Changes Before Confirmation

SKU, quantity, delivery address, and shipping method may be changed while the order is Pending Confirmation, subject to product availability, pricing, serviceability, and payment checks.

## Changes After Confirmation

After confirmation, a change request must be evaluated against allocation and warehouse progress. Changes become increasingly restricted after Allocated, Picked, Packed, and Shipped states.

## Quantity Changes

Increasing quantity requires additional stock and may require additional payment or credit. Decreasing quantity may move a retailer line into a lower discount slab and trigger repricing.

## SKU Changes

Replacing one SKU with another is a cancellation and addition, not a simple description edit. The replacement has its own inventory, price, tax, pack, and handling conditions.

## Address Changes

An address change may alter warehouse routing, carrier, freight, tax treatment, and delivery estimate. Address changes after shipment require carrier approval and may not be possible.

## Split and Merge Requests

Orders may be split for stock or logistics reasons. Combining confirmed orders is not guaranteed because reservations, payments, invoices, and shipments may already be separate.

## Audit Trail

Approved changes should record requester, timestamp, original value, new value, reason, approver where needed, and any pricing or payment impact.

## Shipped Orders

Once shipped, changes are handled through delivery exception, return, or refusal processes. Do not edit historical line items to make the original shipment appear different.

