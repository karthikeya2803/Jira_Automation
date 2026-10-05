# OpenProject issue intake

A small HTML/CSS/JavaScript form and Python standard-library backend that creates OpenProject work packages using API v3.

## Run locally

1. Copy `.env.example` to `.env`.
2. Set `OPENPROJECT_DEMO_MODE=true` to test without an OpenProject account, or set your OpenProject URL, API key, project ID, and work-package type ID for live issue creation.
3. Run `python app.py` from this directory.
4. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The backend uses the API key as a bearer token. Keep `.env` private and do not commit it. The application name, business impact, and description are combined into the created work package's description; priority is matched to the corresponding position in the OpenProject instance's active priority list.

## Test without an OpenProject account

In `.env`, set:

```env
OPENPROJECT_DEMO_MODE=true
```

The other OpenProject settings are not needed in demo mode. Restart `python app.py`, submit the form, and the response will clearly say that the issue is a demo. Demo work packages are saved locally in `data/demo_work_packages.json`; they are not sent to OpenProject. The `data/` folder is excluded from version control.

PowerShell setup:

```powershell
Copy-Item .env.example .env
notepad .env
python app.py
```

`GET /api/health` reports whether the OpenProject settings are present without revealing the API key. `POST /api/issues` validates the form and creates a work package. The app returns an explicit configuration or API error if it cannot create the work package.

## Finding the required IDs

- **Project ID:** use the numeric ID of the target project from its OpenProject API resource or URL.
- **Type ID:** use the numeric ID of the work-package type enabled for that project. The project's types are available from the `types` link in `GET /api/v3/projects/{project_id}`.
- **API key:** create an API token for an OpenProject account with permission to add work packages to that project.

The account's work-package permissions and required custom fields are controlled by your OpenProject instance. If your project requires custom fields, those field values need to be added to the form and mapped to the instance's custom-field API properties.

OpenProject API documentation: [API introduction](https://www.openproject.org/docs/api/introduction/) and [Work Packages endpoint](https://www.openproject.org/docs/api/endpoints/work-packages/).
