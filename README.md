# Lead Intelligence CRM – Social House Learning

A cloud-integrated Lead Management and Analytics CRM built to help Social House Learning manage, monitor and track its lead pipeline through a centralized dashboard.

## 1. Project Overview

Lead Intelligence CRM is a web-based application designed to simplify lead management and provide an organized overview of the sales pipeline.

The application allows users to create, view, update, delete, search and filter lead records. It also provides analytical insights into lead distribution, conversion rates and recent activities.

Instead of relying on manually shared Excel files, the application uses Google Sheets as its primary cloud-based data storage system.

## 2. Key Features

- **Dashboard & Analytics:** Total leads, new leads, converted leads and conversion rate.
- **Lead Management:** Create, edit and permanently delete lead records.
- **Lead Directory:** Search leads by name, email or company.
- **Status Tracking:** Track leads through New, Contacted, Qualified, Converted and Lost stages.
- **Pipeline Visualization:** View lead distribution across different stages.
- **Cloud Synchronization:** Store and retrieve records through Google Sheets.
- **Local JSON Mirror:** Maintain a local JSON copy of lead records.
- **Data Import:** Import existing JSON backup records into Google Sheets while skipping duplicates.
- **Input Validation:** Validate email addresses and prevent duplicate email records.

## 3. Technologies Used

| Technology | Purpose |
|---|---|
| Python | Core application logic |
| Streamlit | Interactive web interface and dashboard |
| Google Sheets | Primary cloud-based data storage |
| Google Apps Script | Backend API for spreadsheet operations |
| Pandas | Data processing and analytics |
| Requests | HTTP communication with Google Apps Script |
| HTTPX | Asynchronous lead import |
| Python-dotenv | Environment configuration |
| JSON | Local data backup and synchronization |

## 4. Why Google Sheets Instead of Excel?

Excel is commonly used by organizations to maintain lead databases. However, traditional Excel-based workflows often involve manually sharing files, managing multiple versions and synchronizing changes.

For this project, Google Sheets was selected because it offers:

- Centralized cloud-based data storage.
- Real-time collaboration between team members.
- Access to the latest records from different devices.
- Integration with applications through Google Apps Script APIs.
- Reduced dependency on manually exchanging spreadsheet files.

The goal was to transform an existing spreadsheet-based workflow into an application-driven CRM system.

Google Sheets acts as the primary database, while the Streamlit application communicates with it through a deployed Google Apps Script Web App.

A local JSON mirror is also maintained for backup and data migration purposes.

## 5. Application Architecture

**Data Flow:**

Streamlit Frontend → Python Application Logic → Google Apps Script Web App API → Google Sheets

The application also maintains a local JSON mirror:

Google Sheets → Python Synchronization Logic → `data/leads.json`

### Main Components

1. **Frontend:** Streamlit provides the dashboard, forms, navigation and lead directory.
2. **Application Logic:** Python handles validation, CRUD operations, filtering and analytics.
3. **API Layer:** Google Apps Script receives GET and POST requests and performs spreadsheet operations.
4. **Primary Storage:** Google Sheets stores the lead records.
5. **Local Backup:** `data/leads.json` maintains a local representation of the records.

## 6. Database Setup and Configuration

This project does not require a separate SQL database installation.

Google Sheets is used as the primary database.

### Step 1: Create a Google Spreadsheet

1. Open Google Sheets.
2. Create a new spreadsheet.
3. Create a sheet for storing lead records.
4. Configure the columns:

`id, name, email, phone, business_name, status, created_at, updated_at`

### Step 2: Configure Google Apps Script

1. Open Extensions → Apps Script from the spreadsheet.
2. toggle add a file named Code.gs ---> paste code.js in file ----> click deploy ---> new devloyment ---> anyone-->  you will get web app url 
6. Copy the deployed Web App URL ending in `/exec`.

### Step 3: Configure Environment Variables

Create a `.env` file in the project root:

```env
SHL_SHEETS_API_URL=YOUR_GOOGLE_APPS_SCRIPT_WEB_APP_URL
```

Keep this file private and never commit credentials or private configuration to GitHub.

### Step 4: Local JSON Backup

The application automatically maintains:

```text
data/
└── leads.json
```

This file stores a local JSON representation of the lead records.

Existing records can also be imported into Google Sheets through the application's Import Local JSON Backup feature.

## 7. Installation and Execution

### Prerequisites

- Python 3.10 or newer.
- Google account.
- Google Spreadsheet.
- Deployed Google Apps Script Web App.

### Step 1: Clone the Repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd YOUR_PROJECT_FOLDER
```

### Step 2: Create a Virtual Environment

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install streamlit pandas requests httpx python-dotenv
```

### Step 4: Configure the Environment

Create `.env` and add your Google Apps Script Web App URL.

### Step 5: Run the Application

```bash
streamlit run app.py
```

Open the local URL displayed in your terminal, usually:

`http://localhost:8501`

## 8. Challenges Faced

During development, I encountered and addressed several practical challenges:

**1. Google Sheets API Integration**

Connecting a Streamlit application with Google Sheets required a separate API layer. I used Google Apps Script as a lightweight backend to handle spreadsheet operations through HTTP requests.

**2. API Communication and Deployment**

Handling HTTP responses, deployment URLs, redirects and JSON response validation required careful implementation.

**3. Data Synchronization**

Maintaining consistency between Google Sheets and the local JSON backup required synchronization after create, update, delete and import operations.

**4. Duplicate Lead Prevention**

Duplicate records could affect analytics and lead management. I implemented email-based duplicate checks and UUID-based record identification.

**5. Data Formatting**

Phone numbers can lose formatting or leading zeros when interpreted as numerical values in spreadsheets. I addressed this by storing phone numbers as text.

**6. Performance Optimization**

I implemented Streamlit caching, reusable HTTP sessions and concurrent requests with a maximum of five simultaneous imports to improve responsiveness and reduce unnecessary API calls.

**7. User Interface Design**

Creating a readable and consistent CRM interface required custom CSS styling, dashboard components, navigation and interactive data tables.

## 9. Future Improvements

- Role-based access for administrators and team members.
- Authentication and authorization.
- Advanced lead assignment and follow-up reminders.
- Automated email and WhatsApp notifications.
- Exportable analytical reports.
- Improved audit logging and synchronization conflict handling.
- Migration to PostgreSQL if the application scales beyond spreadsheet-based storage.

## 10. Conclusion

The project demonstrates how an existing spreadsheet-based lead management workflow can be transformed into a centralized, cloud-integrated CRM application.

By combining Python, Streamlit, Google Apps Script and Google Sheets, the application provides a practical solution for managing leads, tracking pipeline performance and accessing centralized records without requiring a dedicated database server.

