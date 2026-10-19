# Order Lifecycle and Status Rules

## Purpose

Order status describes fulfilment progress. Payment status and shipment status are separate and must not be inferred from order status alone.

## Standard States

### Pending Confirmation

The order request exists but pricing, payment authorization, stock, address, or account conditions may still require validation. Stock is not guaranteed.

### Confirmed

Commercial and account checks have passed. Confirmation does not always mean warehouse stock is already reserved.

### Allocated

Eligible warehouse stock has been assigned. Cancellation may no longer be available without review.

### Picked

Warehouse staff have collected the order lines. Quantity or SKU changes require an operational exception.

### Packed

Goods have been packaged and labelled for shipment. Carrier handover may still be pending.

### Shipped

The carrier has accepted the shipment or a valid handover event has been recorded. A tracking number should normally be available.

### Delivered

Delivery has been recorded. Delivered does not necessarily mean Paid for a retailer using credit terms.

## Exception States

### Cancelled

The order was stopped before successful fulfilment. Shipment fields should be blank unless a shipment was created and then recalled, which requires an exception note.

### Returned

Goods were delivered and later entered an approved return process. Return status should not erase the original shipment or delivery history.

## Status Consistency Rules

- Delivery date cannot precede shipment date.
- Shipment date cannot precede order date.
- Cancelled orders normally have no delivery date.
- Returned orders should have evidence of prior delivery.
- Payment status may be Paid, Pending, Voided, Refunded, or Partially Refunded depending on events.
- An estimated delivery date is not proof of delivery.

## Split Orders

One order may create several shipments. The order can remain partially fulfilled while individual shipments have different tracking and delivery events. Support should explain whether the status refers to the whole order or one shipment.

