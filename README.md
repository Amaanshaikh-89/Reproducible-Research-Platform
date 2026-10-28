# Reproducible Research Platform with Containerized Artifacts, Lineage and Policy Gates

A web-based platform for executing research experiments in isolated Docker containers, tracking experiment provenance, managing artifacts, visualizing lineage, comparing experiment runs, and validating results through policy gates.

## 1. Project Overview

Research experiments can be difficult to reproduce when code versions, datasets, execution parameters, software environments, and generated artifacts are not tracked consistently.

The **Reproducible Research Platform** addresses these challenges by providing a centralized environment to execute experiments, preserve execution metadata, inspect generated artifacts, and compare historical runs.

The platform combines a FastAPI backend, a React frontend, SQLite persistence, and Docker-based experiment execution.

## 2. Objectives

- Execute experiments inside Docker containers.
- Record experiment runs and their execution status.
- Track code, dataset, configuration, and artifact checksums.
- Store experiment metadata and run history persistently.
- Manage and download generated artifacts.
- Visualize relationships between experiments, runs, and artifacts.
- Compare experiment runs using recorded metrics and provenance information.
- Validate execution results using policy gates.
- Generate downloadable provenance reports.
- Maintain an audit trail of important platform activities.
- Support safe deletion of experiments and artifacts.

## 3. Technology Stack

| Component | Technology |
|---|---|
| Frontend | React, Vite, JavaScript |
| Backend | Python, FastAPI |
| Database | SQLite |
| Containerization | Docker |
| API communication | HTTP and REST-style endpoints |
| Testing | pytest |
| Frontend build | npm and Vite |

## 4. System Architecture

The application follows a frontend-backend architecture.

```text
                 User
                  |
                  v
          React + Vite Frontend
                  |
             HTTP Requests
                  |
                  v
           FastAPI Backend
           /      |       \
          v       v        v
      SQLite    Docker   Services
      Database  Runner   / Logic
          |       |        |
          |       v        |
          |   Experiment   |
          |   Execution    |
          |       |        |
          v       v        v
       Run Records, Artifacts,
       Provenance, Policy Checks
                  |
                  v
          Lineage and Reports
                  |
                  v
             Web Interface
```

The frontend communicates with the FastAPI backend. The backend manages experiment metadata, coordinates container execution, stores records in SQLite, and provides APIs for artifact management, provenance reports, policy checks, comparison, and audit events.

## 5. Core Features

### 5.1 Experiment Management

Users can create experiments, save Python source and JSON input, and view or edit saved definitions through the web interface. Experiment records organize executions and their associated results.

### 5.2 Containerized Execution

The platform runs each experiment's saved Python code inside a restricted Docker container. The runner handles execution outcomes, records run status, and attempts container cleanup after completion or failure. An experiment with blank code remains saved and receives a failed run instructing the user to edit and save code before trying again.

Containerization helps isolate experiment execution from the host environment. It does not, by itself, guarantee complete security against arbitrary untrusted code.

### 5.3 Experiment Run History

Each execution is represented by a run record. The platform stores execution status and relevant metadata so users can inspect historical runs and their associated results.

### 5.4 Artifact Registry

Generated artifacts are registered and associated with their corresponding runs. The registry supports artifact inspection, preview, and download.

Artifact integrity checks compare a stored checksum with the checksum calculated from the actual file. The platform also supports safe artifact deletion with path validation and handling for shared artifact files.

### 5.5 Provenance Tracking

Provenance metadata helps describe how an experiment run was produced. Depending on the available run data, it includes:

- Code SHA-256 checksum
- Dataset SHA-256 checksum
- Execution parameters
- Configuration checksum
- Docker image information
- Docker image digest, when available
- Run metrics and artifact metadata

This information supports traceability and helps users investigate differences between experiment executions.

### 5.6 Lineage Visualization

The lineage interface visualizes relationships among experiment runs and artifacts. Users can inspect how recorded entities are connected and open artifact previews from the graph where supported.

### 5.7 Run Comparison

The comparison feature evaluates two historical runs using recorded metrics and provenance information.

The comparison verdict can indicate:

- **MATCHED:** The required recorded information matches according to the implemented comparison checks.
- **DIFFERENT:** A relevant difference is detected.
- **INSUFFICIENT PROVENANCE:** The available information is not sufficient to establish a match.

A MATCHED verdict does not guarantee identical results across every possible execution environment.

### 5.8 Policy Gates

Policy checks evaluate selected requirements associated with an experiment run, including:

- Execution succeeded
- Code provenance recorded
- Artifact integrity

The interface displays the recorded check results and associated explanations.

### 5.9 Provenance Reports

The platform provides downloadable JSON provenance reports for individual runs. Reports contain relevant run information, recorded provenance, metrics, artifact metadata, and policy results.

Sensitive values and filesystem paths are subject to the implemented report-redaction rules.

### 5.10 Audit Trail

The Audit Trail maintains a persistent record of selected activities, including provenance report generation and comparison verification.

Audit events are stored in SQLite and can be inspected through the web interface. The audit trail is an application-level record and is not designed to be cryptographically tamper-proof.

### 5.11 Deletion and Data Management

The platform supports deletion of registered artifacts and experiments with confirmation.

Artifact deletion removes the registry entry and attempts file cleanup only when the file is not shared by another artifact record. Experiment deletion handles associated runs, artifact records, and policy checks while preserving audit events and clearing references to deleted runs.

## 6. Project Structure

The principal project components include:

```text
reproducible-research-platform/
├── app/
│   ├── main.py
│   ├── database.py
│   └── services/
│       ├── runner.py
│       ├── policies.py
│       └── reports.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api.js
│   │   └── components/
│   │       └── AuditTrail.jsx
│   ├── package.json
│   └── ...
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_runner.py
│   └── test_reports.py
├── artifacts/
├── requirements.txt
└── README.md
```

This is a representative structure of the principal components. Keep the actual directories and filenames in your repository consistent with your current implementation.

## 7. Prerequisites

Install the following software:

- Python with support for the project's dependencies
- Node.js and npm
- Docker Desktop
- Git (optional, for version control)

On Windows, ensure Docker Desktop is running before testing containerized experiment execution.

## 8. Installation and Setup

### Step 1: Open the project directory

Open a terminal in the project root directory.

### Step 2: Create a Python virtual environment

```powershell
python -m venv .venv
```

Activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can invoke the virtual environment's Python executable directly instead.

### Step 3: Install backend dependencies

```powershell
python -m pip install -r requirements.txt
```

### Step 4: Install frontend dependencies

```powershell
cd frontend
npm install
cd ..
```

### Step 5: Start Docker Desktop

Open Docker Desktop and verify that the Docker engine is running before executing experiments.

## 9. Running the Application

### Start the backend

From the project root:

```powershell
uvicorn app.main:app --reload
```

The backend should be available at:

`http://127.0.0.1:8000`

### Start the frontend

Open a second terminal:

```powershell
cd frontend
npm run dev
```

Open the frontend URL displayed by Vite, normally:

`http://localhost:5173`

### API documentation

FastAPI provides interactive API documentation at:

`http://127.0.0.1:8000/docs`

### Health check

Open:

`http://127.0.0.1:8000/health`

The endpoint can be used to check the backend's health response.

**Configuration note:** Confirm that the frontend API base URL, database path, artifact storage directory, and Docker settings match the configuration in your actual project before distributing this README.

## 10. Testing

### Run backend tests

From the project root:

```powershell
python -m pytest -q -rs
```

The test suite covers selected API behavior, runner behavior, and report generation.

### Build the frontend

From the project root:

```powershell
cd frontend
npm run build
```

A successful production build confirms that Vite can compile the frontend.

### Manual acceptance testing

Verify the following through the running application:

1. Backend health and frontend startup.
2. Experiment creation and listing.
3. Successful experiment execution and run history.
4. Policy gate results.
5. Artifact preview, download, integrity verification, and deletion.
6. Experiment deletion and associated record handling.
7. Lineage graph rendering.
8. Run comparison and comparison audit event recording.
9. Provenance report download.
10. Audit Trail display and navbar refresh.

Record the actual test results before submitting the project.

## 11. Security and Reliability Considerations

The platform includes execution failure handling, Docker container cleanup attempts, artifact path validation, checksum verification, report redaction, and input/error handling.

The following limitations should be considered:

- The Audit Trail is not cryptographically tamper-proof.
- Docker isolation is not a guarantee against every possible container escape or host-level risk.
- The runner executes saved user-submitted Python code; Docker isolation does not make arbitrary untrusted code risk-free.
- Cleanup may not complete after a hard host or process termination.
- Reproducibility depends on the completeness and accuracy of recorded metadata and the availability of the original inputs and environment.
- Filesystem validation cannot eliminate every possible race condition in a concurrently modified local filesystem.

## 12. Future Enhancements

Potential future improvements include:

- Stronger isolation for untrusted experiment workloads.
- Cryptographically verifiable or externally anchored audit records.
- Configurable policy rules and richer policy enforcement history.
- More detailed experiment metrics and comparison visualizations.
- Dataset version management and immutable artifact storage.
- Automated integration testing with real Docker containers.
- Deployment support for shared or remote research environments.

These are proposed enhancements and should not be represented as existing features unless they are implemented.

## 13. Conclusion

The Reproducible Research Platform provides an integrated workflow for containerized experiment execution, artifact management, provenance tracking, lineage visualization, run comparison, policy checks, and audit-event recording.

By combining persistent metadata with execution records and integrity checks, the platform helps researchers inspect experiment history and assess whether recorded results can be reproduced or compared.

The project demonstrates the application of containerization, backend API development, database persistence, frontend visualization, and software testing to research reproducibility.

---

**Project:** Reproducible Research Platform with Containerized Artifacts, Lineage and Policy Gates

**Backend:** FastAPI

**Frontend:** React + Vite

**Database:** SQLite

**Execution environment:** Docker
