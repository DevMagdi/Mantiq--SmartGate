# Face enrollment & vehicle registration guide

This guide covers everything an operator needs to make recognition reliable:
registering residents and vehicles, enrolling faces that pass the quality gates,
keeping the gallery healthy and handling erasure requests.

---

## 1. Why quality gates exist

A blurry 120×120 crop does not just fail to match — it produces an embedding
that sits close to *everyone* and causes false accepts. GateVision therefore
assesses every enrolment photo before storing an embedding:

| Issue code | Severity | Meaning | What to do |
| --- | --- | --- | --- |
| `low_resolution` | error | Image or face smaller than `face_min_resolution` (default 200 px) | move closer / use a better camera |
| `no_face` | error | No face detected | frontal photo, no sunglasses/mask |
| `multiple_faces` | error | More than one face | crop to the resident only |
| `face_too_small` | error | Face occupies < `face_min_face_ratio` of the frame | fill ~40 % of the frame with the face |
| `face_distorted` | error | Extreme aspect/pose | straighten the photo |
| `blurry` | error | Laplacian sharpness < `face_min_blur` (default 40) | hold still, refocus |
| `too_dark` / `too_bright` | error | Mean brightness outside 30–235 | add light / avoid backlight |
| `duplicate_face` | warning | ≥ `duplicate_similarity_threshold` (0.90) of an existing embedding | the resident is already enrolled |
| `low_quality_score` | error | Composite score < `face_min_quality` (default 55) | retake the photo |

Admins can relax or tighten these per compound through the settings API
(`vision.face_min_quality`, `vision.face_min_blur`, …) — but keep them strict:
the cheapest way to improve accuracy is better enrolment photos.

---

## 2. Register the resident

Residents belong to a **unit** (household). Create the unit first if needed:

```bash
# 1) unit (if the compound has none yet)
curl -X POST localhost:8000/api/v1/compounds/$COMPOUND/units \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"building": "B", "unit_number": "204", "floor": 2, "bedrooms": 3}'

# 2) resident (create_account=true also creates the resident portal login)
curl -X POST localhost:8000/api/v1/residents -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"compound_id": "'$COMPOUND'", "unit_id": "'$UNIT'",
       "full_name": "Mona Adel", "national_id": "29001011234567",
       "phone": "+20 100 123 4567", "email": "mona@example.com",
       "role_in_unit": "owner", "status": "active",
       "create_account": true, "account_password": "ChangeMe@2026"}'
```

Leave out `create_account` when the gate staff manages the resident; residents
with an account can enrol their own face later from
**My household → Face enrollment**.

---

## 3. Enrol a face (correct workflow)

**Step 1 — check the photo before storing it** (residents may only check
themselves; staff can check anyone in their compound):

```bash
curl -X POST localhost:8000/api/v1/faces/quality-check \
  -H "Authorization: Bearer $OFFICER" \
  -F file=@mona.jpg -F resident_id=$RESIDENT_ID | jq
```

```json
{
  "passed": true,
  "score": 82.5,
  "face_count": 1,
  "width": 1080, "height": 1080,
  "face_ratio": 0.41, "blur": 96.3, "brightness": 148.2,
  "duplicate_similarity": null,
  "issues": []
}
```

A rejected photo returns `passed: false` plus actionable `issues` (code,
message, hint). Fix the photo instead of lowering the thresholds.

**Step 2 — enrol** (multipart; `overwrite=true` replaces the resident's existing
embeddings, which is what you want after a haircut/beard change):

```bash
curl -X POST localhost:8000/api/v1/faces/enroll \
  -H "Authorization: Bearer $OFFICER" \
  -F resident_id=$RESIDENT_ID -F overwrite=true -F file=@mona.jpg | jq
```

Rejections are explicit:

| HTTP | `error.code` | Meaning |
| --- | --- | --- |
| 400 | `enrollment_rejected` | quality gate failed — `details` contains the report |
| 400 | `embedding_limit_reached` | already has `max_embeddings_per_resident` (default 3) active embeddings |
| 400 | `no_face_detected` | detector found nothing |
| 403 | `forbidden` | resident tried to enrol someone else |

**How many photos?** One good frontal photo per resident is enough for a lane
camera. Add a second (different lighting) if the same resident enters from a
glare-heavy or night lane. Never enrol more than the policy allows: extra
embeddings widen the acceptance region.

**Step 3 — refresh the gallery for the running worker:**

```bash
curl -X POST localhost:8000/api/v1/cv/refresh-gallery -H "Authorization: Bearer $OFFICER"
curl -s localhost:8000/api/v1/cv/gallery -H "Authorization: Bearer $OFFICER" | jq
```

`/cv/gallery` reports `total_embeddings`, `active_embeddings`,
`enrolled_residents`, the model and the active threshold.

---

## 4. Keep the gallery healthy

* **Audit duplicates** — `duplicate_face` warnings during enrolment mean the
  resident already has a usable embedding.
* **Prune stale/low-quality embeddings** (dry-run first):

```bash
curl -X POST localhost:8000/api/v1/faces/prune -H "Authorization: Bearer $OFFICER" \
  -H "Content-Type: application/json" \
  -d '{"compound_id": "'$COMPOUND'", "max_per_resident": 2, "dry_run": true}'
```

The response lists what would be deactivated (`kept`, `deactivated`,
`residents`). Re-run with `"dry_run": false` to apply — the service always keeps
the **highest-quality** embedding per resident.

* **Erase on request** — `DELETE /faces/{id}` removes the row and the stored
  image; `POST /faces/{id}/deactivate` keeps the row for audit while removing it
  from matching. Both are audited.
* **Re-enrol after big appearance changes** with `overwrite=true`.

---

## 5. Register vehicles (plates)

Egyptian plates can be entered in Arabic, Latin or mixed form; GateVision
normalises them (`ب ج ١٢٣٤` → `BG1234`, `4821 ABC` → digits-first) and matches
using learned variants, so the exact spelling in the registry does not need to
match the camera read character-for-character.

```bash
curl -X POST localhost:8000/api/v1/vehicles -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"compound_id": "'$COMPOUND'", "resident_id": "'$RESIDENT'",
       "plate_number": "4821 ABC", "make": "Toyota", "model": "Corolla",
       "color": "White", "vehicle_type": "car", "status": "active"}'
```

Rules:

* One `plate_number` per vehicle; the API stores both the display form and the
  normalised key used by the decision engine.
* Suspending a vehicle (`{"status": "suspended"}`) denies it at the barrier —
  it does not delete the history.
* Guests' vehicles go through **permits** (`POST /permits` with `vehicle_id`,
  `start_at`, `end_at`, `max_entries`), not the resident registry.
* Test the round trip before go-live:

```bash
curl -X POST localhost:8000/api/v1/access-logs/manual -H "Authorization: Bearer $OFFICER" \
  -H "Content-Type: application/json" \
  -d '{"gate_id": "'$GATE'", "plate_number": "4821 ABC", "decision": "allow",
       "reason": "Registry smoke test", "open_gate": false}'
```

The returned log must reference the vehicle and the resident — if `vehicle_id`
is `null`, the plate did not match. Check the plate in the dashboard
(**My household → Vehicles**) and look for stray characters.

---

## 6. Operating tips

| Situation | Action |
| --- | --- |
| Resident wears glasses/sunglasses daily | enrol a second photo with them |
| Children/short adults | mount the face camera lower or use a wider lens |
| Face camera mounted at > 2.5 m | add a second camera; otherwise faces are `face_too_small` |
| Resident refuses biometrics | rely on plates (vehicles) or a visitor permit; the API never requires a face |
| Visitor needs access | `POST /visitors` + permit; never enrol visitors in the resident gallery |
| GDPR/biometric erasure request | `DELETE /faces/{id}` for every embedding of the subject, log the case id |

All enrolment, rejection, pruning and deletion actions are audited with the
actor, timestamp and quality report.
