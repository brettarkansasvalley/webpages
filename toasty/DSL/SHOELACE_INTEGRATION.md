# Shoelace Web Components Integration Guide

## Overview

This document describes how to integrate the DSL queries with Shoelace web components to build the new Toast reporting interface.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Shoelace Web UI                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Report     │  │   Data       │  │   Filter     │       │
│  │   Selector   │  │   Table      │  │   Controls   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ HTTP/JSON
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              JAQ JSON Loader Server                         │
│                   (localhost:3000)                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  DSL Query Engine                                    │   │
│  │  - SELECT, WHERE, JOIN, GROUP BY                   │   │
│  │  - Aggregation: sum, count, avg, min, max          │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                          ▼                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  SQLite Database                                     │   │
│  │  - json_objects table                                │   │
│  │  - Toast API data                                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Shoelace Components

### 1. Report Selector (sl-select)

```html
<sl-select label="Select Report" id="report-selector">
  <sl-option value="employees">Employees</sl-option>
  <sl-option value="labor_hours">Labor Hours Daily</sl-option>
  <sl-option value="labor_shifts">Labor Shifts Detailed</sl-option>
  <sl-option value="cash_tips">Cash Tips Per Shift</sl-option>
  <sl-option value="cash_summary">Cash Summary</sl-option>
  <sl-option value="gratuity">Gratuity Per Shift</sl-option>
</sl-select>
```

### 2. Data Table (sl-table or custom)

```html
<sl-card id="results-card">
  <div slot="header">
    <span id="report-title">Report Results</span>
    <sl-button id="export-btn" variant="primary" size="small">
      <sl-icon name="download"></sl-icon>
      Export CSV
    </sl-button>
  </div>
  
  <div id="table-container">
    <!-- Dynamic table will be inserted here -->
  </div>
  
  <div slot="footer">
    <sl-pagination id="pagination" total="100" page="1" page-size="25"></sl-pagination>
  </div>
</sl-card>
```

### 3. Filter Panel (sl-drawer or sl-details)

```html
<sl-details summary="Filters" open>
  <sl-input id="filter-date-start" type="date" label="Start Date"></sl-input>
  <sl-input id="filter-date-end" type="date" label="End Date"></sl-input>
  
  <sl-select id="filter-employee" label="Employee" multiple clearable>
    <!-- Populated dynamically -->
  </sl-select>
  
  <sl-select id="filter-job" label="Job Title" multiple clearable>
    <!-- Populated dynamically -->
  </sl-select>
  
  <sl-button id="apply-filters" variant="primary">Apply Filters</sl-button>
  <sl-button id="clear-filters">Clear</sl-button>
</sl-details>
```

### 4. Loading State (sl-spinner, sl-skeleton)

```html
<div id="loading-overlay" hidden>
  <sl-spinner style="font-size: 2rem;"></sl-spinner>
  <p>Loading data...</p>
</div>
```

### 5. Query Editor (sl-textarea with JSON highlighting)

```html
<sl-details summary="Advanced: Edit DSL Query">
  <sl-textarea
    id="dsl-editor"
    rows="20"
    label="DSL Query"
    placeholder="Enter your DSL query here..."
  ></sl-textarea>
  <sl-button id="run-custom-query" variant="primary">Run Query</sl-button>
</sl-details>
```

## JavaScript Integration

### DSL Query Service

```javascript
class DSLQueryService {
  constructor(baseUrl = 'http://localhost:3000') {
    this.baseUrl = baseUrl;
  }

  async executeQuery(dslQuery) {
    const response = await fetch(`${this.baseUrl}/query/dsl`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: JSON.stringify(dslQuery) })
    });
    
    if (!response.ok) {
      throw new Error(`Query failed: ${response.statusText}`);
    }
    
    return await response.json();
  }

  async exportToCSV(dslQuery, filename) {
    const response = await fetch(`${this.baseUrl}/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: JSON.stringify(dslQuery),
        format: 'csv',
        filename: filename
      })
    });
    
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filename}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  }

  async getSourceFiles() {
    const response = await fetch(`${this.baseUrl}/files`);
    return await response.json();
  }

  async getSchema(sourceFile) {
    const response = await fetch(`${this.baseUrl}/schema?source_file=${sourceFile}`);
    return await response.json();
  }
}
```

### Report Controller

```javascript
class ReportController {
  constructor(queryService) {
    this.queryService = queryService;
    this.reports = {
      employees: {
        name: 'Employees',
        dsl: {
          from: { source_file: 'labor_v1_employees.json', alias: 'emp' },
          select: [
            { expr: 'emp.guid', alias: 'guid' },
            { expr: 'emp.firstName', alias: 'firstName' },
            { expr: 'emp.lastName', alias: 'lastName' },
            { expr: 'emp.email', alias: 'email' }
          ]
        }
      },
      labor_hours: {
        name: 'Labor Hours Daily',
        dsl: {
          from: { source_file: 'labor_v1_timeEntries_20260130.json', alias: 'te' },
          group_by: [
            { field: 'te.businessDate' },
            { field: 'te.employeeReference.guid' }
          ],
          select: [
            { expr: 'te.businessDate', alias: 'date' },
            { expr: 'te.employeeReference.guid', alias: 'employee_guid' },
            { expr: 'count(te.guid)', alias: 'shifts_count' },
            { expr: 'sum(te.regularHours)', alias: 'regular_hours' }
          ]
        }
      }
      // ... more reports
    };
  }

  async loadReport(reportId, filters = {}) {
    const report = this.reports[reportId];
    if (!report) {
      throw new Error(`Unknown report: ${reportId}`);
    }

    // Apply filters to DSL
    const dsl = this.applyFilters(report.dsl, filters);
    
    return await this.queryService.executeQuery(dsl);
  }

  applyFilters(dsl, filters) {
    const filtered = { ...dsl };
    
    if (filters.dateStart || filters.dateEnd) {
      filtered.where = filtered.where || [];
      
      if (filters.dateStart) {
        filtered.where.push({
          field: 'te.businessDate',
          op: '>=',
          value: filters.dateStart.replace(/-/g, '')
        });
      }
      
      if (filters.dateEnd) {
        filtered.where.push({
          field: 'te.businessDate',
          op: '<=',
          value: filters.dateEnd.replace(/-/g, '')
        });
      }
    }
    
    if (filters.employees?.length) {
      filtered.where = filtered.where || [];
      filtered.where.push({
        field: 'te.employeeReference.guid',
        op: 'in',
        values: filters.employees
      });
    }
    
    return filtered;
  }
}
```

### Table Renderer

```javascript
class TableRenderer {
  render(container, data) {
    if (!data.success || !data.rows?.length) {
      container.innerHTML = '<p>No data available</p>';
      return;
    }

    const columns = data.columns;
    const rows = data.rows;

    const table = document.createElement('table');
    table.className = 'data-table';
    
    // Header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    columns.forEach(col => {
      const th = document.createElement('th');
      th.textContent = col;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);
    
    // Body
    const tbody = document.createElement('tbody');
    rows.forEach(row => {
      const tr = document.createElement('tr');
      columns.forEach(col => {
        const td = document.createElement('td');
        td.textContent = row[col] ?? '';
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    
    container.innerHTML = '';
    container.appendChild(table);
  }
}
```

## Example: Complete Report Page

```html
<!DOCTYPE html>
<html>
<head>
  <title>Toast Reports</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@shoelace-style/shoelace@2.12.0/cdn/themes/light.css">
  <script type="module" src="https://cdn.jsdelivr.net/npm/@shoelace-style/shoelace@2.12.0/cdn/shoelace.js"></script>
  <style>
    .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
    .filters { margin-bottom: 20px; }
    .data-table { width: 100%; border-collapse: collapse; }
    .data-table th, .data-table td { padding: 8px; border: 1px solid #ddd; }
    .data-table th { background: #f5f5f5; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Toast Data Reports</h1>
    
    <sl-select label="Select Report" id="report-selector">
      <sl-option value="">-- Select --</sl-option>
      <sl-option value="employees">Employees</sl-option>
      <sl-option value="labor_hours">Labor Hours</sl-option>
      <sl-option value="labor_shifts">Labor Shifts Detailed</sl-option>
      <sl-option value="cash_tips">Cash Tips</sl-option>
      <sl-option value="cash_summary">Cash Summary</sl-option>
    </sl-select>
    
    <div id="loading" hidden>
      <sl-spinner style="font-size: 2rem;"></sl-spinner>
    </div>
    
    <sl-card id="results-card">
      <div slot="header">
        <span id="report-title">Select a report</span>
        <sl-button id="export-btn" variant="primary" size="small" disabled>
          <sl-icon name="download"></sl-icon> Export CSV
        </sl-button>
      </div>
      <div id="table-container">
        <p>Select a report to view data</p>
      </div>
    </sl-card>
  </div>

  <script type="module">
    import { DSLQueryService, ReportController, TableRenderer } from './reporting.js';
    
    const queryService = new DSLQueryService();
    const controller = new ReportController(queryService);
    const renderer = new TableRenderer();
    
    let currentReport = null;
    let currentData = null;
    
    document.getElementById('report-selector').addEventListener('sl-change', async (e) => {
      const reportId = e.target.value;
      if (!reportId) return;
      
      document.getElementById('loading').hidden = false;
      
      try {
        currentData = await controller.loadReport(reportId);
        currentReport = reportId;
        
        document.getElementById('report-title').textContent = 
          controller.reports[reportId].name;
        document.getElementById('export-btn').disabled = false;
        
        renderer.render(
          document.getElementById('table-container'),
          currentData
        );
      } catch (error) {
        document.getElementById('table-container').innerHTML = 
          `<sl-alert variant="danger" open>${error.message}</sl-alert>`;
      } finally {
        document.getElementById('loading').hidden = true;
      }
    });
    
    document.getElementById('export-btn').addEventListener('click', async () => {
      if (!currentReport) return;
      
      const dsl = controller.reports[currentReport].dsl;
      await queryService.exportToCSV(dsl, currentReport);
    });
  </script>
</body>
</html>
```

## Next Steps

1. Create the base HTML/CSS/JS framework
2. Implement the DSL query service
3. Build report-specific components
4. Add advanced filtering UI
5. Implement saved queries feature
6. Add charting/visualization for key metrics
