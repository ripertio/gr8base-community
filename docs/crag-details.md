# Crag Details

This table describes the information that a crag entry can contain in gr8base community. "Mandatory" means the information is required to create a crag entry. Optional photo details are not required unless a photo is added.

| Section | Criterion | Type | Mandatory? | Status |
|---|---|---|---|---|
| Basic information | Crag name | String (max. 160 characters) | Yes | Implemented |
| Basic information | Area name | Reference to area (select an existing area or add a new one) | Yes | Implemented |
| Basic information | Guidebooks | Reference to guidebooks (many-to-many: search and select existing ones or add a new one in a dialog; a crag can be in several guidebooks and a guidebook covers several crags) | No | Implemented |
| Photos | Photo upload | Image file (multiple photos per crag) | No | Implemented |
| Photos | Photo category | Choice (crag, base area, approach, parking, surrounding terrain, other) | No | Implemented |
| Family suitability | Rating for babies (0–1 year) | Number (1–5) | No | Implemented |
| Family suitability | Rating for children (2–4 years) | Number (1–5) | No | Implemented |
| Family suitability | Rating for children aged 5 and older | Number (1–5) | No | Implemented |
| Approach | Walking time to the crag | Number (minutes) | No | Implemented |
| Approach | Approach features | Multiple choice from the feature list, managed in the admin (e.g. rockfall, fall hazard, stroller-friendly) | No | Implemented |
| Approach | Approach assessed | Yes/no: the author checked the approach, so "no features" means none rather than unknown | No | Implemented |
| Base area | Base area features | Multiple choice from the feature list, managed in the admin (e.g. rockfall, fall hazard, stroller-friendly) | No | Implemented |
| Base area | Base area assessed | Yes/no: same meaning as for the approach | No | Implemented |
| Crag | Orientation | Choice (N, NE, E, SE, S, SW, W, NW) | No | Implemented |
| Crag | Coordinates | Latitude and longitude (decimal numbers) | No | Implemented |
| Crag | Parking | String (location details or map link) | No | Implemented |
| Other information | Description | String (free text) | No | Implemented |
| Other information | Family notes | String (free text) | No | Implemented |
| Administration | Status | Choice (draft, pending, published/approved, rejected) | System | Implemented |
| Administration | Created by, created at, updated at | User reference, timestamps | System | Implemented |

## Guidebooks

A guidebook is its own entry, shared between crags. Contributors can create one while editing a crag; staff and Crag Managers can also manage them in the admin.

| Criterion | Type | Mandatory? | Status |
|---|---|---|---|
| Name | String (max. 250 characters) | Yes | Implemented |
| Link | URL | No | Implemented |
| Publication year | Number (1800–2100) | No | Implemented |
| Publisher | String (max. 200 characters) | No | Implemented |
| Cover picture | Image file, re-encoded to WebP (max. 800 pixels) like photos | No | Implemented |

When a new guidebook is added with a name that already exists (ignoring case and extra spaces), the existing guidebook is reused and the details entered are ignored.
