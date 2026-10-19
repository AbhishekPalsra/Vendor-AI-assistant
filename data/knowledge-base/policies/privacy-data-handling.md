# Customer and Retailer Data Handling

## Scope

This guidance covers buyer IDs, names, business names, city, state, phone, email, retailer tier, credit limit, payment terms, discount group, order history, and support evidence.

## Minimum Necessary Use

Use only the information needed for the service request. A product-availability question may require location and buyer type but not a full credit history. A credit request may require finance data but not unrelated support conversations.

## Identity and Authorization

Before disclosing account-specific orders, prices, credit, payments, or contacts, verify that the requester is authorized for the buyer ID. Public policy and general catalog information can be shared without account disclosure.

## Prohibited Disclosure

- Do not reveal one buyer's transactions or pricing to another buyer.
- Do not expose complete payment credentials or banking secrets.
- Do not include unnecessary personal information in operational notes.
- Do not copy claim photographs or identity documents into unrelated systems.

## Contact Corrections

Account contact changes require suitable verification. Record the old value, new value, requester, timestamp, and approval where required. A support conversation alone may not be sufficient for a sensitive account change.

## Synthetic Project Data

Addresses under `sampurna.example` and people in this knowledge base are fictional. Production implementations must replace them with approved data and privacy controls.

## Retention and Deletion

Retention periods depend on legal, tax, financial, contractual, and operational needs. Staff should follow the approved retention schedule rather than deleting transaction or claim records ad hoc.

## RAG Safety

Retrieval systems should enforce access control before returning account-specific chunks or structured records. Vector similarity is not authorization. Sensitive fields should be filtered based on the requester and use case.

