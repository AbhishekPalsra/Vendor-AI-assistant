# Tax and Invoice Rules

## Invoice Content

An invoice should identify seller, buyer information where required, invoice number and date, order reference, SKU or description, quantity, unit price, discount, taxable value, tax rate and amount, total, and payment terms.

## Calculation Sequence

At line level, the standard project calculation is:

1. Gross amount equals quantity multiplied by historical unit price.
2. Discount amount equals gross amount multiplied by discount percentage.
3. Taxable amount equals gross amount minus discount amount.
4. Tax amount equals taxable amount multiplied by tax rate.
5. Line total equals taxable amount plus tax amount.

## Tax Classification

Tax rate depends on product classification and transaction context. Category examples in project data support analysis but do not replace legal tax determination.

## Rounding

Amounts are normally stored to two decimal places. Any invoice-level rounding adjustment should be visible and reproducible.

## Historical Integrity

Changing today's product tax classification or price must not silently change a completed historical invoice. Corrections require an approved credit note, debit note, or restatement process.

## Retailer Information

Retailers must keep invoice and tax details current. A change requested after invoice issuance may require cancellation and reissue only when legally and operationally permitted.

## Disputes

Submit invoice number, buyer ID, order ID, SKU, disputed field or amount, expected treatment, and supporting documents. Continue paying undisputed amounts according to terms unless Finance agrees otherwise.

## Disclaimer

This synthetic project document describes internal data logic and is not legal or tax advice. Production rules require qualified review.

