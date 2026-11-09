# Alfurqan College — Website & School Management Information System

Institutional website and integrated SMIS for **Alfurqan College of Health Sciences and Technology**
(Django 5, server-rendered templates, Bootstrap 5, SQLite → PostgreSQL-ready).

## Quick start

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_institution      # roles, grading, 4 programmes, 172 curriculum courses, fees, templates
python manage.py createsuperuser        # your real Super Administrator account
python manage.py load_demo_data         # OPTIONAL sample data (password: Sample@2026)
python manage.py runserver
```

| Portal | URL | Sign in with |
|---|---|---|
| Website | `/` | — |
| Application Portal | `/apply/` | e-mail |
| Student Portal | `/student/` | matric number or e-mail |
| Staff Portal | `/staff/` | staff ID, username or e-mail |

Remove all sample data at any time: `python manage.py load_demo_data --purge`.
Sample records carry `is_sample=True` and show a **Sample** tag.

## Architecture

```
apps/core          settings singleton, permission registry, audit log, Excel bulk-import framework,
                   generic config CRUD, PDF/Excel helpers, role-adaptive dashboard
apps/accounts      one User model (applicant/student/staff), roles = Django groups, user & role admin
apps/website       public site + CMS (posts, slides, highlights, leadership, contact messages)
apps/academics     departments, programmes (duration/levels/weighting per programme), sessions,
                   semesters, courses, prerequisites, practical requirements, allocations, calendar
apps/admissions    application periods, applications, O'Levels, documents, decisions, offer → student
apps/students      student records, statuses, documents, history, promotion, matric numbers
apps/registration  course registration rules (deadline, credits, prerequisites, duplicates, approval)
apps/results       grading schemes, score sheets, approval workflow, GPA/CGPA, transcripts, broadsheets
apps/bursary       fee schedule, invoices, instalments, adjustments, refunds, gateways, webhooks, receipts
apps/notifications templated in-app/e-mail/SMS notifications, broadcast
apps/reports       report registry (screen / Excel / PDF)
```

Business rules live in each app's `services.py`. Student self-service, staff-assisted screens and
Excel bulk imports all call the **same services**, and every action records the actor; when the actor
is not the student/applicant, it is logged as "on behalf of" (audit log, registration and application history).

## Key design points

- **Nothing institutional is hard-coded**: fees, grading bands, pass marks, CA/exam weighting, durations,
  level names, matric/application number formats, statuses, document types, notification wording and
  roles/permissions are all edited from the Staff Portal.
- **Permissions**: 35 capabilities (`apps/core/models.py: CAPABILITIES`) grouped into roles
  (Super Administrator, Administrator, Academic Officer, Admission Officer, Bursary Officer, HOD, Lecturer).
- **Bulk operations** (template → upload → validation → preview → confirm → summary → failed-rows download):
  new students, student updates, status changes, applicant registration, admission decisions, offer
  acceptance, course registration, score sheets, payments.
- **Results**: Lecturer → HOD → approving officer → publish. Locked results can only be changed with
  the `manage_all_results` permission and a reason; every score change is audited (old → new).
- **Payments**: never marked successful from the browser. Callbacks and webhooks both trigger a
  server-to-server verification (amount and currency checked), completion is idempotent, webhook
  signatures are verified (Paystack HMAC-SHA512 / Flutterwave hash). A sandbox gateway exists for
  development only (`ALLOW_SANDBOX_GATEWAY`).

## Production

Copy `.env.example` to `.env`, set `DJANGO_DEBUG=false`, a secret key, gateway keys and e-mail settings,
then `python manage.py collectstatic`. Set `DATABASE_ENGINE=postgresql` to switch database.
Configure gateway webhooks to `https://alfurqancollege.com.ng/payments/webhook/paystack/` (or `/flutterwave/`).

## Tests

```bash
python manage.py test apps
```

47 tests cover the grading engine, GPA/CGPA, result workflow and audit, registration rules, fee
generation, instalments, refunds, online-payment verification and webhooks, admission conversion,
bulk imports and access control.

## Items for the College to confirm

Run `python manage.py setup_institution` to print the list; summary:

- Contact details, vision, mission, core values, objectives, history and the Provost's welcome message
  are drafts/empty (marked `[DRAFT]`). A dashboard banner remains until "Content reviewed" is ticked.
- Curriculum discrepancies kept exactly as printed (see `apps/academics/curricula.py: SOURCE_NOTES`):
  ND Nutrition Y1S2 lists 21 units vs printed total 25 and repeats code GNS 101; ND HIM Y2S2 lists 16 vs 18;
  CHE 208 title "Modified Essential New Board Care".
- Public Health Technology has no letter-grade table in its curriculum → NBTE 9-band scale applied.
- Nutrition & HIM curricula do not state a CA/exam split → 30/70 configured.
- Fee amounts are the reference values supplied; whether the examination fee is per session or per
  semester should be confirmed (currently per session).
- Departments are one per programme; adjust to the College's actual structure.
