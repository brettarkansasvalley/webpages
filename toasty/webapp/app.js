// Toasty - Toast Data Analytics App
// Fetches data from JAQ JSON Loader Server and renders reports
//
// JUMP TAGS (for direct navigation):
// #dashboard - Main dashboard page
// #calendar - Calendar view with all dates
// #calendar-grid - The calendar grid itself
// #calendar-workers - Workers list for selected date
// #server-tips - Server tips assignment page
// #locations-detected - Detected locations from shifts
// #server-tips-form - Server tips entry form
// #bartender-tips - Bartender tips page
// #bartender-tips-form - Bartender tips entry form
// #payouts - Payouts management page
// #payouts-totals - Unpaid totals section
// #payouts-assignments - Worker assignments section
// #payouts-preview - Distribution preview table
// #reports - Reports listing page
// #query - Query builder page
// #report-results - Report results page
//
// Example URL: http://localhost:8080/#calendar

// Use relative URLs to work with Nginx reverse proxy
const JAQ_SERVER = '/jaq';
const API_BASE = '/webapp/api'; // Local API for tips/payouts

// Report query definitions
const REPORT_QUERIES = {
    orders_overview: {
        name: "Orders Overview",
        description: "Basic order information and totals (Jan 30, 2026). Use the Query Builder to query specific dates.",
        query: {
            "from": { "source_file": "orders_full_20260130.json", "alias": "o" },
            "select": [
                {"expr": "o.guid", "alias": "Order_GUID"},
                {"expr": "o.displayNumber", "alias": "Order_Number"},
                {"expr": "o.openedDate", "alias": "Opened_Date"},
                {"expr": "o.businessDate", "alias": "Business_Date"},
                {"expr": "o.approvalStatus", "alias": "Status"},
                {"expr": "o.source", "alias": "Source"}
            ],
            "order_by": [{"field": "o.openedDate", "direction": "DESC"}],
            "limit": 100
        }
    },
    employees: {
        name: "Employees",
        description: "Employee list with contact information.",
        query: {
            "from": { "source_file": "labor_v1_employees.json", "alias": "e" },
            "select": [
                {"expr": "e.guid", "alias": "Employee_GUID"},
                {"expr": "e.firstName", "alias": "First_Name"},
                {"expr": "e.lastName", "alias": "Last_Name"},
                {"expr": "e.email", "alias": "Email"},
                {"expr": "e.phoneNumber", "alias": "Phone"}
            ],
            "order_by": [{"field": "e.lastName", "direction": "ASC"}],
            "limit": 200
        }
    },
    time_entries: {
        name: "Time Entries",
        description: "Employee time clock entries.",
        query: {
            "from": { "source_file": "labor_v1_timeEntries_20260130.json", "alias": "t" },
            "select": [
                {"expr": "t.employeeGuid", "alias": "Employee_GUID"},
                {"expr": "t.inDate", "alias": "Clock_In"},
                {"expr": "t.outDate", "alias": "Clock_Out"},
                {"expr": "t.regularHours", "alias": "Regular_Hours"},
                {"expr": "t.overtimeHours", "alias": "Overtime_Hours"}
            ],
            "order_by": [{"field": "t.inDate", "direction": "DESC"}],
            "limit": 100
        }
    }
};

// State management
let currentReport = null;
let currentResults = [];
let charts = {};

// API base URL for local backend (via Nginx proxy)
const LOCAL_API = '/webapp/api';

// Data caches
let WORKERS = [];
let BUCKETS = [];

// Calendar state
let calendarState = {
    currentDate: new Date(),
    selectedDate: null,
    availableDates: new Set(),
    dailyStats: {},  // Format: { "2026-01-30": { count: 150, total: 4500.50 } }
    workersForDate: [],
    filteredWorkers: []
};

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    checkConnection();
    loadDashboardMetrics();
    setDefaultDates();
    initializeTipsPages();
    initializeCalendar();
    
    // Populate workers for default date on Server Tips page
    setTimeout(() => updateServerTipsWorkersForDate(), 100);
    
    // Handle hash-based navigation
    handleHashNavigation();
    initializeTypeToFilter();
});

// Parse URL parameters from hash fragment or query string
function parseUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const hashParams = new URLSearchParams();
    
    // Also check for params in hash (e.g., #bartender-tips?bucket=am_bar)
    const hash = window.location.hash;
    if (hash.includes('?')) {
        const hashQuery = hash.split('?')[1];
        const hp = new URLSearchParams(hashQuery);
        hp.forEach((value, key) => hashParams.set(key, value));
    }
    
    // Merge: hash params take precedence over query params
    const result = {};
    params.forEach((value, key) => result[key] = value);
    hashParams.forEach((value, key) => result[key] = value);
    
    return result;
}

// Update URL with current page parameters (for sharing links)
function updateUrlWithParams(pageId, params) {
    if (!pageId) return;
    
    const url = new URL(window.location.href);
    const hashBase = url.hash.split('?')[0];
    
    // Build new hash with params
    const hashParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value) hashParams.set(key, value);
    });
    
    const newHash = hashParams.toString() 
        ? `${hashBase}?${hashParams.toString()}`
        : hashBase;
    
    // Update URL without reloading
    window.history.replaceState(null, null, `${url.pathname}${url.search}${newHash}`);
}

// Apply URL parameters to the appropriate page
function applyUrlParams(pageId, params) {
    if (!params || Object.keys(params).length === 0) return;
    
    switch (pageId) {
        case 'bartender-tips':
            applyBartenderTipsParams(params);
            break;
        case 'server-tips':
            applyServerTipsParams(params);
            break;
        case 'payouts':
            applyPayoutsParams(params);
            break;
    }
}

// Apply params to Bartender Tips page
function applyBartenderTipsParams(params) {
    const dateInput = document.getElementById('bartenderTipsDate');
    const bucketSelect = document.getElementById('bartenderTipsBucket');
    
    let hasParams = false;
    
    if (params.business_date && dateInput) {
        dateInput.value = params.business_date;
        hasParams = true;
    }
    if (params.date && dateInput) {
        dateInput.value = params.date;
        hasParams = true;
    }
    if (params.bucket && bucketSelect) {
        bucketSelect.value = params.bucket;
        hasParams = true;
    }
    
    // Auto-fetch data if we have the required params
    if (hasParams && dateInput?.value && bucketSelect?.value) {
        setTimeout(() => loadBartenderDefaults(), 300);
    }
}

// Apply params to Server Tips page
function applyServerTipsParams(params) {
    const dateInput = document.getElementById('serverTipsDate');
    const bucketSelect = document.getElementById('serverTipsBucket');
    const workerSelect = document.getElementById('serverTipsWorker');
    
    let hasAutoFetchParams = false;
    
    if (params.business_date && dateInput) {
        dateInput.value = params.business_date;
        // Trigger worker dropdown update when date is set
        setTimeout(() => updateServerTipsWorkersForDate(), 100);
        hasAutoFetchParams = true;
    }
    if (params.date && dateInput) {
        dateInput.value = params.date;
        // Trigger worker dropdown update when date is set
        setTimeout(() => updateServerTipsWorkersForDate(), 100);
        hasAutoFetchParams = true;
    }
    if (params.bucket && bucketSelect) {
        bucketSelect.value = params.bucket;
    }
    if (params.worker && workerSelect) {
        // Worker selection requires the dropdown to be populated first
        setTimeout(() => {
            const workerValue = params.worker.replace(/\s+/g, '_');
            workerSelect.value = workerValue;
            
            // Auto-fetch data from Toast after worker is selected
            // This simulates clicking the "Fetch from Toast" button
            setTimeout(() => {
                fetchServerTipsFromToast();
                showToast(`Loading data for ${params.worker} on ${dateInput.value}...`, 'info');
            }, 800);
        }, 500);
    }
}

// Apply params to Payouts page
function applyPayoutsParams(params) {
    const dateInput = document.getElementById('payoutDate');
    const bucketSelect = document.getElementById('payoutBucket');
    
    let hasParams = false;
    
    // Clear any existing preview when applying new params
    const previewSection = document.getElementById('payoutPreviewSection');
    const previewMeta = document.getElementById('payoutPreviewMeta');
    const previewTable = document.getElementById('payoutPreviewTable');
    if (previewSection) previewSection.style.display = 'none';
    if (previewMeta) previewMeta.innerHTML = '';
    if (previewTable) previewTable.innerHTML = '';
    
    if (params.business_date && dateInput) {
        dateInput.value = params.business_date;
        hasParams = true;
    }
    if (params.date && dateInput) {
        dateInput.value = params.date;
        hasParams = true;
    }
    if (params.bucket && bucketSelect) {
        bucketSelect.value = params.bucket;
        hasParams = true;
    }
    
    // Auto-load data if we have the required params
    if (hasParams && dateInput?.value && bucketSelect?.value) {
        setTimeout(() => loadPayoutsData(), 300);
    }
}

// Handle hash-based navigation
function handleHashNavigation() {
    const hash = window.location.hash.slice(1); // Remove #
    const hashBase = hash.split('?')[0]; // Remove query params from hash
    
    if (hashBase) {
        // Map hash to page ID
        const pageMap = {
            'dashboard': 'dashboard',
            'calendar': 'calendar',
            'reports': 'reports',
            'worker-report': 'worker-report',
            'suggest': 'suggest',
            'query': 'query',
            'fetch': 'fetch',
            'server-tips': 'server-tips',
            'bartender-tips': 'bartender-tips',
            'payouts': 'payouts'
        };
        
        const pageId = pageMap[hashBase];
        if (pageId) {
            // Update nav active state without calling showPage (to avoid loop)
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.remove('active');
                // Check if this nav item's onclick contains the pageId
                if (item.getAttribute('onclick')?.includes(`'${pageId}'`)) {
                    item.classList.add('active');
                }
            });
            
            // Show the page
            document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
            const page = document.getElementById(`${pageId}-page`);
            if (page) {
                page.classList.add('active');
                // If calendar page, ensure it's rendered
                if (pageId === 'calendar') {
                    renderCalendar();
                }
            }
            
            // Apply URL parameters to the page
            const params = parseUrlParams();
            applyUrlParams(pageId, params);
        }
    }
    
    // Listen for hash changes
    window.addEventListener('hashchange', () => {
        handleHashNavigation();
    });
}

// Check connection to JAQ server
async function checkConnection() {
    const statusEl = document.getElementById('connectionStatus');
    try {
        const response = await fetch(`${JAQ_SERVER}/stats`);
        if (response.ok) {
            const stats = await response.json();
            statusEl.className = 'connection-status connected';
            statusEl.innerHTML = `
                <sl-icon name="check-circle"></sl-icon>
                <span>${stats.total_objects?.toLocaleString() || 'Connected'} records</span>
            `;
        } else {
            throw new Error('Server error');
        }
    } catch (error) {
        statusEl.className = 'connection-status error';
        statusEl.innerHTML = `
            <sl-icon name="exclamation-triangle"></sl-icon>
            <span>Connection failed</span>
        `;
    }
}

// Initialize tips pages - fetch real data from API
async function initializeTipsPages() {
    try {
        // Fetch workers from API
        const workersResp = await fetch(`${LOCAL_API}/workers`);
        WORKERS = await workersResp.json();
        
        // Fetch buckets from API
        const bucketsResp = await fetch(`${LOCAL_API}/buckets`);
        BUCKETS = await bucketsResp.json();
    } catch (error) {
        console.log('API not available, using fallback data');
        // Fallback data if API is not running
        WORKERS = ["Jordan Bailey", "Sierrah Bartz", "Tony Beliel", "Jillian Boyert", "Alex Cheatham"];
        BUCKETS = [
            { id: "am_bar", name: "AM Bar" },
            { id: "sunset", name: "Sunset Bar" },
            { id: "westwing", name: "West Wing" },
            { id: "eastwing", name: "East Wing" }
        ];
    }
    
    // Populate worker selects
    const workerSelects = ['serverTipsWorker', 'bartenderTipsWorker'];
    workerSelects.forEach(id => {
        const select = document.getElementById(id);
        if (select) {
            select.innerHTML = '<sl-option value="">Select worker</sl-option>';
            WORKERS.forEach(w => {
                const option = document.createElement('sl-option');
                // Use slugified value to avoid spaces, store actual name in data attribute
                option.value = w.replace(/\s+/g, '_');
                option.setAttribute('data-worker-name', w);
                option.textContent = w;
                select.appendChild(option);
            });
        }
    });

    // Populate bucket selects
    const bucketSelects = ['serverTipsBucket', 'payoutBucket'];
    bucketSelects.forEach(id => {
        const select = document.getElementById(id);
        if (select) {
            select.innerHTML = '<sl-option value="">Select location</sl-option>';
            BUCKETS.forEach(b => {
                const option = document.createElement('sl-option');
                option.value = b.id;
                option.textContent = b.name;
                select.appendChild(option);
            });
        }
    });

    // Populate bar select (AM Bar and Sunset Bar)
    const barSelect = document.getElementById('bartenderTipsBar');
    if (barSelect) {
        barSelect.innerHTML = '<sl-option value="">Select bar</sl-option>';
        BUCKETS.filter(b => b.id === 'am_bar' || b.id === 'sunset').forEach(b => {
            const option = document.createElement('sl-option');
            option.value = b.id;
            option.textContent = b.name;
            barSelect.appendChild(option);
        });
    }

    // Initialize payouts assignments
    initializePayoutAssignments();
    
    // Add date/bucket change listeners for Payouts to clear preview
    const payoutDate = document.getElementById('payoutDate');
    const payoutBucket = document.getElementById('payoutBucket');
    const payoutShowAll = document.getElementById('payoutShowAll');
    
    function clearPayoutPreview() {
        const previewSection = document.getElementById('payoutPreviewSection');
        const previewMeta = document.getElementById('payoutPreviewMeta');
        const previewTable = document.getElementById('payoutPreviewTable');
        if (previewSection) previewSection.style.display = 'none';
        if (previewMeta) previewMeta.innerHTML = '';
        if (previewTable) previewTable.innerHTML = '';
    }
    
    if (payoutDate) {
        payoutDate.addEventListener('sl-change', () => {
            clearPayoutPreview();
            loadPayoutsData();
        });
    }
    if (payoutBucket) {
        payoutBucket.addEventListener('sl-change', () => {
            clearPayoutPreview();
            loadPayoutsData();
        });
    }
    if (payoutShowAll) {
        payoutShowAll.addEventListener('sl-change', () => {
            clearPayoutPreview();
            loadPayoutsData();
        });
    }
    
    // Add date change listener for Server Tips to update worker dropdown
    const serverTipsDate = document.getElementById('serverTipsDate');
    if (serverTipsDate) {
        serverTipsDate.addEventListener('sl-change', () => {
            updateServerTipsWorkersForDate();
            updateServerTipsUrl();
        });
    }
    
    // Add worker and bucket change listeners to update URL
    const serverTipsWorker = document.getElementById('serverTipsWorker');
    const serverTipsBucket = document.getElementById('serverTipsBucket');
    if (serverTipsWorker) {
        serverTipsWorker.addEventListener('sl-change', updateServerTipsUrl);
    }
    if (serverTipsBucket) {
        serverTipsBucket.addEventListener('sl-change', async () => {
            updateServerTipsUrl();
            const workerSelect = document.getElementById('serverTipsWorker');
            const selectedValue = workerSelect?.value;
            const selectedOption = workerSelect?.querySelector(`sl-option[value="${selectedValue}"]`);
            const worker = selectedOption?.getAttribute('data-worker-name') || selectedValue;
            const date = document.getElementById('serverTipsDate')?.value;
            if (worker && date) {
                await fetchServerTipsFromToast();
            }
        });
    }
}

// Store workers data for the current date
let currentDateWorkers = [];

// Update worker dropdown on Server Tips page based on selected date
async function updateServerTipsWorkersForDate() {
    const dateInput = document.getElementById('serverTipsDate');
    const workerSelect = document.getElementById('serverTipsWorker');
    if (!dateInput || !workerSelect) return;
    
    // If no date is set, try to use the most recent date with data
    if (!dateInput.value) {
        try {
            const datesResponse = await fetch(`${LOCAL_API}/dates`);
            const dates = await datesResponse.json();
            if (dates && dates.length > 0) {
                // Sort dates and pick the most recent
                dates.sort();
                dateInput.value = dates[dates.length - 1];
            } else {
                return; // No dates available
            }
        } catch (error) {
            console.error('Failed to fetch available dates:', error);
            return;
        }
    }
    
    const date = dateInput.value;
    
    try {
        // Fetch workers who worked on this date
        const response = await fetch(`${LOCAL_API}/dates/${date}/workers`);
        const workers = await response.json();
        currentDateWorkers = workers;
        
        console.log(`Loaded ${workers.length} workers for ${date}`);
        
        // Filter to only server-type workers (those with shifts at actual locations)
        // OR include all workers if location data is not available (orders fallback)
        const hasLocationData = workers.some(w => 
            w.shifts && w.shifts.some(s => {
                const loc = (s.location || '').toLowerCase();
                return loc && loc !== 'unknown' && loc !== 'other';
            })
        );
        
        const serverWorkers = workers.filter(w => {
            // If no location data available (orders fallback), include all workers with tips
            if (!hasLocationData) {
                return true;
            }
            // Otherwise, include workers who have shifts at bucket locations
            return w.shifts && w.shifts.some(s => {
                const loc = (s.location || '').toLowerCase();
                return loc.includes('bar') || loc.includes('wing') || loc.includes('am_bar') || loc.includes('sunset') || loc.includes('westwing') || loc.includes('eastwing');
            });
        });
        
        console.log(`Filtered to ${serverWorkers.length} server workers`);
        
        // Save current selection
        const currentValue = workerSelect.value;
        
        // Repopulate dropdown
        workerSelect.innerHTML = '<sl-option value="">Select worker</sl-option>';
        serverWorkers.forEach(w => {
            const option = document.createElement('sl-option');
            option.value = w.name.replace(/\s+/g, '_');
            option.setAttribute('data-worker-name', w.name);
            option.textContent = `${w.name} (${w.total_hours.toFixed(2)} hrs)`;
            workerSelect.appendChild(option);
        });
        
        // Restore selection if still valid
        if (currentValue) {
            const stillExists = serverWorkers.some(w => w.name.replace(/\s+/g, '_') === currentValue);
            if (stillExists) {
                workerSelect.value = currentValue;
            }
        }
        
        // Remove existing listener to avoid duplicates, then add new one
        workerSelect.removeEventListener('sl-change', autoSelectBucketForWorker);
        workerSelect.addEventListener('sl-change', autoSelectBucketForWorker);
    } catch (error) {
        console.error('Failed to load workers for date:', error);
    }
}

// Update URL when server tips selections change
function updateServerTipsUrl() {
    const dateInput = document.getElementById('serverTipsDate');
    const workerSelect = document.getElementById('serverTipsWorker');
    const bucketSelect = document.getElementById('serverTipsBucket');
    
    const date = dateInput?.value;
    const workerValue = workerSelect?.value;
    const bucket = bucketSelect?.value;
    
    // Get actual worker name from option
    let worker = workerValue;
    if (workerSelect && workerValue) {
        const opt = workerSelect.querySelector(`sl-option[value="${workerValue}"]`);
        worker = opt?.getAttribute('data-worker-name') || workerValue;
    }
    
    if (date || worker) {
        const params = { business_date: date };
        if (worker) params.worker = worker;
        if (bucket) params.bucket = bucket;
        updateUrlWithParams('server-tips', params);
    }
}

// Auto-select bucket when worker is selected
function autoSelectBucketForWorker() {
    const workerSelect = document.getElementById('serverTipsWorker');
    const bucketSelect = document.getElementById('serverTipsBucket');
    if (!workerSelect || !bucketSelect) return;
    
    const selectedValue = workerSelect.value;
    if (!selectedValue) return;
    
    const workerName = selectedValue.replace(/_/g, ' ');
    const worker = currentDateWorkers.find(w => w.name === workerName);
    
    if (worker && worker.locations && worker.locations.length > 0) {
        // Map location name to bucket ID
        const location = worker.locations[0]; // Use first location
        const bucketMap = {
            'AM Bar': 'am_bar',
            'Sunset Bar': 'sunset',
            'West Wing': 'westwing',
            'East Wing': 'eastwing'
        };
        const bucketId = bucketMap[location];
        if (bucketId) {
            bucketSelect.value = bucketId;
            // Update URL with the auto-selected bucket
            updateServerTipsUrl();
        }
    }
}

// Initialize payout assignment boxes
function initializePayoutAssignments() {
    const container = document.getElementById('payoutAssignments');
    if (!container) return;

    const destinations = ['Bartender', 'Busser', 'Expo', 'Runner'];
    container.innerHTML = '';

    destinations.forEach(dest => {
        const box = document.createElement('div');
        box.className = 'assignment-box';
        box.innerHTML = `
            <h4>${dest} Assignments</h4>
            <div style="margin-bottom: 8px;">
                <sl-select id="splitMode-${dest}" size="small" value="even" help-text="Split mode">
                    <sl-option value="even">Even Split</sl-option>
                    <sl-option value="hourly">Hourly Split</sl-option>
                </sl-select>
            </div>
            <div class="assignment-list" id="assign-${dest}">
                ${WORKERS.map(w => `
                    <label class="assignment-item">
                        <sl-checkbox name="assign_${dest}" value="${w}"></sl-checkbox>
                        <span>${w}</span>
                    </label>
                `).join('')}
            </div>
            <div class="assignment-count" id="count-${dest}">0 assigned</div>
        `;
        container.appendChild(box);
    });

    // Add change listeners
    destinations.forEach(dest => {
        const list = document.getElementById(`assign-${dest}`);
        if (list) {
            list.addEventListener('sl-change', () => updateAssignmentCount(dest));
        }
    });
    
    // Add listener for "Show all workers" switch
    const showAllSwitch = document.getElementById('payoutShowAll');
    if (showAllSwitch) {
        showAllSwitch.addEventListener('sl-change', async () => {
            const bucket = document.getElementById('payoutBucket')?.value;
            const date = document.getElementById('payoutDate')?.value;
            if (bucket && date) {
                const showAll = showAllSwitch.checked;
                const params = new URLSearchParams({ bucket, date, show_all: showAll ? '1' : '0' });
                const resp = await fetch(`${LOCAL_API}/payouts/suggested-assignments?${params}`);
                const data = await resp.json();
                updatePayoutAssignmentBoxesFromSuggestions(data.assignments || {});
            }
        });
    }
}

function getPayoutSplitModes() {
    const modes = {};
    ['Bartender', 'Busser', 'Expo', 'Runner'].forEach(dest => {
        const el = document.getElementById(`splitMode-${dest}`);
        const val = (el?.value || 'even').toLowerCase();
        modes[dest] = (val === 'hourly') ? 'hourly' : 'even';
    });
    return modes;
}

function allocateCentsByWeights(totalAmount, workers, weightByWorker) {
    const centsTotal = Math.round((Number(totalAmount) || 0) * 100);
    if (workers.length === 0) return [];

    // If no amount, return explicit zero rows.
    if (centsTotal === 0) {
        return workers.map(worker => ({ worker, cents: 0 }));
    }

    const weights = workers.map(w => Math.max(0, Number(weightByWorker?.[w] || 0)));
    const totalWeight = weights.reduce((a, b) => a + b, 0);

    // Fallback to equal split when weights are absent/zero.
    const effWeights = totalWeight > 0 ? weights : workers.map(() => 1);
    const effTotalWeight = effWeights.reduce((a, b) => a + b, 0);

    const rows = workers.map((worker, i) => {
        const raw = (centsTotal * effWeights[i]) / effTotalWeight;
        const base = Math.floor(raw);
        const frac = raw - base;
        return { worker, base, frac, cents: base };
    });

    let remainder = centsTotal - rows.reduce((s, r) => s + r.base, 0);
    rows.sort((a, b) => b.frac - a.frac);
    for (let i = 0; i < rows.length && remainder > 0; i += 1) {
        rows[i].cents += 1;
        remainder -= 1;
    }

    rows.sort((a, b) => workers.indexOf(a.worker) - workers.indexOf(b.worker));
    return rows.map(r => ({ worker: r.worker, cents: r.cents }));
}

async function buildPayoutDistributions() {
    const bucket = document.getElementById('payoutBucket')?.value;
    const date = document.getElementById('payoutDate')?.value;

    const amounts = {
        Bartender: parseFloat(document.getElementById('payoutBartenderAmount')?.value || 0),
        Busser: parseFloat(document.getElementById('payoutBusserAmount')?.value || 0),
        Expo: parseFloat(document.getElementById('payoutExpoAmount')?.value || 0),
        Runner: parseFloat(document.getElementById('payoutRunnerAmount')?.value || 0)
    };

    const assignments = {};
    ['Bartender', 'Busser', 'Expo', 'Runner'].forEach(dest => {
        const list = document.getElementById(`assign-${dest}`);
        assignments[dest] = list
            ? Array.from(list.querySelectorAll('sl-checkbox[checked]')).map(cb => cb.value)
            : [];
    });

    const splitModes = getPayoutSplitModes();
    const hourlyNeeded = ['Bartender', 'Busser', 'Expo', 'Runner']
        .filter(dest => splitModes[dest] === 'hourly' && (assignments[dest] || []).length > 0);

    let hoursByDest = {};
    if (hourlyNeeded.length > 0) {
        try {
            const resp = await fetch(`${LOCAL_API}/payouts/role-hours`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ date, bucket, assignments })
            });
            if (resp.ok) {
                const data = await resp.json();
                hoursByDest = data.hours || {};
            }
        } catch (e) {
            console.warn('Failed to load role-hours; falling back to even split:', e);
        }
    }

    const distributions = [];
    let grandTotal = 0;

    Object.entries(assignments).forEach(([dest, workers]) => {
        const amount = amounts[dest] || 0;
        if (!workers || workers.length === 0) return;

        const mode = splitModes[dest] || 'even';
        const weightMap = mode === 'hourly' ? (hoursByDest[dest] || {}) : {};
        const allocations = allocateCentsByWeights(amount, workers, weightMap);

        allocations.forEach(a => {
            const val = a.cents / 100;
            distributions.push({
                worker: a.worker,
                destination: dest,
                amount: val.toFixed(2),
                split_mode: mode,
                hours: Number(weightMap?.[a.worker] || 0)
            });
            grandTotal += val;
        });
    });

    return {
        bucket,
        date,
        amounts,
        assignments,
        splitModes,
        hoursByDest,
        distributions,
        grandTotal: Number(grandTotal.toFixed(2))
    };
}

// Update assignment count
function updateAssignmentCount(dest) {
    const list = document.getElementById(`assign-${dest}`);
    const countEl = document.getElementById(`count-${dest}`);
    if (list && countEl) {
        const checked = list.querySelectorAll('sl-checkbox[checked]').length;
        countEl.textContent = `${checked} assigned`;
    }
}

function getPayoutAssignmentWorkers() {
    const workers = new Set();
    ['Bartender', 'Busser', 'Expo', 'Runner'].forEach(dest => {
        const list = document.getElementById(`assign-${dest}`);
        if (!list) return;
        list.querySelectorAll('sl-checkbox').forEach(cb => {
            if (cb.value) workers.add(cb.value);
        });
    });
    return Array.from(workers).sort();
}

function encodePayoutWorkerValue(name) {
    return encodeURIComponent(name || '');
}

function decodePayoutWorkerValue(value) {
    try {
        return decodeURIComponent(value || '');
    } catch (e) {
        return value || '';
    }
}

function refreshPayoutRoleCorrectionWorkerOptions() {
    const select = document.getElementById('payoutRoleCorrectionWorker');
    if (!select) return;
    const prior = decodePayoutWorkerValue(select.value || '');
    const workers = getPayoutAssignmentWorkers();
    let html = '<sl-option value="">Select worker</sl-option>';
    workers.forEach(w => {
        html += `<sl-option value="${encodePayoutWorkerValue(w)}">${w}</sl-option>`;
    });
    select.innerHTML = html;
    if (prior && workers.includes(prior)) select.value = encodePayoutWorkerValue(prior);
}

async function loadPayoutRoleCorrections() {
    const date = document.getElementById('payoutDate')?.value;
    const bucket = document.getElementById('payoutBucket')?.value;
    const listEl = document.getElementById('payoutRoleCorrectionList');
    if (!date || !bucket || !listEl) return;
    try {
        const params = new URLSearchParams({ date, bucket });
        const resp = await fetch(`${LOCAL_API}/payouts/role-corrections?${params}`);
        const data = await resp.json();
        const rows = data.corrections || [];
        if (!rows.length) {
            listEl.textContent = 'No role corrections saved for this date/bucket.';
            return;
        }
        listEl.innerHTML = rows
            .map(r => `${r.worker} -> ${r.corrected_role}${r.bucket ? '' : ' (global)'}`)
            .join('<br>');
    } catch (e) {
        listEl.textContent = 'Failed to load role corrections.';
    }
}

async function savePayoutRoleCorrection() {
    const worker = decodePayoutWorkerValue(document.getElementById('payoutRoleCorrectionWorker')?.value);
    const correctedRole = document.getElementById('payoutRoleCorrectionRole')?.value;
    const date = document.getElementById('payoutDate')?.value;
    const bucket = document.getElementById('payoutBucket')?.value;
    if (!worker || !correctedRole || !date || !bucket) {
        showToast('Select worker, corrected role, date, and bucket', 'warning');
        return;
    }
    try {
        const resp = await fetch(`${LOCAL_API}/payouts/role-corrections`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ worker, corrected_role: correctedRole, date, bucket })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to save correction');
        await loadPayoutRoleCorrections();
        showToast('Role correction saved', 'success');
    } catch (e) {
        showToast(e.message || 'Failed to save role correction', 'error');
    }
}

async function clearPayoutRoleCorrection() {
    const worker = decodePayoutWorkerValue(document.getElementById('payoutRoleCorrectionWorker')?.value);
    const date = document.getElementById('payoutDate')?.value;
    const bucket = document.getElementById('payoutBucket')?.value;
    if (!worker || !date || !bucket) {
        showToast('Select worker, date, and bucket', 'warning');
        return;
    }
    try {
        const params = new URLSearchParams({ worker, date, bucket });
        const resp = await fetch(`${LOCAL_API}/payouts/role-corrections?${params}`, { method: 'DELETE' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to clear correction');
        await loadPayoutRoleCorrections();
        showToast('Role correction cleared', 'success');
    } catch (e) {
        showToast(e.message || 'Failed to clear role correction', 'error');
    }
}

// Set default date range
function setDefaultDates() {
    const today = new Date().toISOString().split('T')[0];
    ['queryEndDate', 'serverTipsDate', 'bartenderTipsDate', 'payoutDate'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = today;
    });
    const startDate = new Date();
    startDate.setDate(startDate.getDate() - 30);
    const startEl = document.getElementById('queryStartDate');
    if (startEl) startEl.value = startDate.toISOString().split('T')[0];
}

// Navigation
function showPage(event, pageId) {
    // Allow Ctrl+click or Cmd+click to open in new tab
    if (event && (event.ctrlKey || event.metaKey)) {
        // Let the browser handle the click (open in new tab)
        return true;
    }
    
    // Prevent default navigation for normal clicks
    if (event) {
        event.preventDefault();
    }
    
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    if (event && event.target) {
        event.target.closest('.nav-item')?.classList.add('active');
    }
    
    document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
    const page = document.getElementById(`${pageId}-page`);
    if (page) page.classList.add('active');
    
    // Update URL hash for direct linking
    if (window.location.hash !== `#${pageId}`) {
        window.history.pushState(null, null, `#${pageId}`);
    }
    
    // If calendar page, ensure it's rendered
    if (pageId === 'calendar') {
        renderCalendar();
    }
    if (pageId === 'fetch') {
        loadAutoFetchStatus();
    }
}

// Show/hide loading
function showLoading(message = 'Loading...') {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        const p = overlay.querySelector('p');
        if (p) p.textContent = message;
        overlay.style.display = 'flex';
    }
}

function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.style.display = 'none';
}

// Show toast notification
function showToast(message, variant = 'primary') {
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toastMessage');
    if (toast && toastMessage) {
        toast.variant = variant;
        toastMessage.textContent = message;
        toast.show();
    }
}

function isEditableTarget(target) {
    if (!target) return false;
    const tag = (target.tagName || '').toLowerCase();
    if (['input', 'textarea', 'select'].includes(tag)) return true;
    if (target.isContentEditable) return true;
    if (target.closest && target.closest('sl-input, sl-textarea, sl-select')) return true;
    return false;
}

function getActivePageFilterInput() {
    const activePage = document.querySelector('.page.active');
    if (!activePage) return null;

    // Prefer explicit filter/search bars.
    const preferredSelectors = [
        '#calendarWorkerFilter',
        'sl-input[placeholder*="Filter"]',
        'sl-input[placeholder*="filter"]',
        'sl-input[placeholder*="Search"]',
        'sl-input[placeholder*="search"]'
    ];

    for (const sel of preferredSelectors) {
        const el = activePage.querySelector(sel);
        if (el && !el.disabled) return el;
    }
    return null;
}

function initializeTypeToFilter() {
    document.addEventListener('keydown', (e) => {
        if (e.defaultPrevented) return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (isEditableTarget(e.target)) return;

        const filterInput = getActivePageFilterInput();
        if (!filterInput) return;

        // Printable keys should append to filter input and trigger filtering.
        if (e.key.length === 1) {
            e.preventDefault();
            const current = String(filterInput.value || '');
            filterInput.value = current + e.key;
            filterInput.focus();
            filterInput.dispatchEvent(new Event('input', { bubbles: true }));
            filterInput.dispatchEvent(new Event('sl-input', { bubbles: true }));
            return;
        }

        // Allow quick correction even when field isn't focused.
        if (e.key === 'Backspace') {
            e.preventDefault();
            const current = String(filterInput.value || '');
            filterInput.value = current.slice(0, -1);
            filterInput.focus();
            filterInput.dispatchEvent(new Event('input', { bubbles: true }));
            filterInput.dispatchEvent(new Event('sl-input', { bubbles: true }));
        }
    });
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// =====================
// CALENDAR FUNCTIONS
// =====================

async function initializeCalendar() {
    // Fetch available dates
    try {
        const response = await fetch(`${LOCAL_API}/dates`);
        const dates = await response.json();
        calendarState.availableDates = new Set(dates);
        
        // Fetch order stats for the current month
        await fetchOrderStatsForMonth();
        
        renderCalendar();
    } catch (error) {
        console.error('Failed to load calendar dates:', error);
    }
}

// Fetch order counts and totals for the currently visible month
async function fetchOrderStatsForMonth() {
    const year = calendarState.currentDate.getFullYear();
    const month = calendarState.currentDate.getMonth();
    
    // Build list of dates in the visible month
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const datesToFetch = [];
    
    for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        if (calendarState.availableDates.has(dateStr)) {
            datesToFetch.push(dateStr);
        }
    }
    
    // Fetch stats for each date (parallel)
    await Promise.all(datesToFetch.map(async (dateStr) => {
        try {
            const stats = await fetchOrderStatsForDate(dateStr);
            if (stats) {
                calendarState.dailyStats[dateStr] = stats;
            }
        } catch (error) {
            console.warn(`Failed to fetch stats for ${dateStr}:`, error);
        }
    }));
}

// Fetch order stats for a single date from JAQ
async function fetchOrderStatsForDate(dateStr) {
    // Convert date to filename format: 2026-01-30 -> orders_full_20260130.json
    const datePart = dateStr.replace(/-/g, '');
    const filename = `orders_full_${datePart}.json`;
    
    try {
        // Fetch all orders for the date and calculate stats client-side
        // JAQ stores orders with json_data field containing the actual order JSON
        // Add cache buster to prevent stale data
        const cacheBuster = Date.now();
        const response = await fetch(`${JAQ_SERVER}/query?source_file=${filename}&limit=10000&_=${cacheBuster}`);
        
        if (!response.ok) {
            // File might not exist in JAQ
            return null;
        }
        
        const rows = await response.json();
        
        if (Array.isArray(rows)) {
            let count = 0;
            let total = 0;
            
            for (const row of rows) {
                if (row.json_data) {
                    try {
                        const order = JSON.parse(row.json_data);
                        const checks = order.checks || [];
                        const orderTotal = checks.reduce((sum, check) => {
                            return sum + (check.totalAmount || 0);
                        }, 0);
                        total += orderTotal;
                        count++;
                    } catch (e) {
                        // Skip invalid JSON
                    }
                }
            }
            
            return { count, total };
        }
        
        return null;
    } catch (error) {
        // Silently fail - file might not exist
        console.warn(`Error fetching stats for ${dateStr}:`, error);
        return null;
    }
}

// Debug function to check calendar data
function debugCalendarData() {
    console.log('=== Calendar Debug ===');
    console.log('Available dates:', Array.from(calendarState.availableDates).slice(-10));
    console.log('Daily stats:', Object.keys(calendarState.dailyStats));
    console.log('Current month:', calendarState.currentDate.toISOString().slice(0, 7));
}

function renderCalendar() {
    const container = document.getElementById('calendarGrid');
    if (!container) return;
    
    const year = calendarState.currentDate.getFullYear();
    const month = calendarState.currentDate.getMonth();
    
    // Update month label
    const monthLabel = document.getElementById('currentMonthLabel');
    if (monthLabel) {
        monthLabel.textContent = new Date(year, month).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    }
    
    // Get first day of month and number of days
    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const daysInPrevMonth = new Date(year, month, 0).getDate();
    
    let html = '';
    
    // Day headers
    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    dayNames.forEach(day => {
        html += `<div class="calendar-header">${day}</div>`;
    });
    
    // Previous month days
    for (let i = firstDay - 1; i >= 0; i--) {
        const day = daysInPrevMonth - i;
        html += `<div class="calendar-day other-month"><span class="calendar-day-number">${day}</span></div>`;
    }
    
    // Current month days
    for (let day = 1; day <= daysInMonth; day++) {
        const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const hasData = calendarState.availableDates.has(dateStr);
        const isSelected = calendarState.selectedDate === dateStr;
        const stats = calendarState.dailyStats[dateStr];
        
        let classes = 'calendar-day';
        if (hasData) classes += ' has-data';
        if (isSelected) classes += ' selected';
        
        // Build stats display
        let statsHtml = '';
        if (stats) {
            statsHtml = `
                <div class="calendar-stats">
                    <div class="calendar-stat-count">${stats.count} orders</div>
                    <div class="calendar-stat-total">$${stats.total.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0})}</div>
                </div>
            `;
        } else if (hasData) {
            statsHtml = '<span class="calendar-day-info">Orders</span>';
        }
        
        html += `
            <div class="${classes}" onclick="selectCalendarDate('${dateStr}')" data-date="${dateStr}">
                <span class="calendar-day-number">${day}</span>
                ${statsHtml}
            </div>
        `;
    }
    
    // Next month days to fill grid
    const remainingCells = 42 - (firstDay + daysInMonth);
    for (let day = 1; day <= remainingCells; day++) {
        html += `<div class="calendar-day other-month"><span class="calendar-day-number">${day}</span></div>`;
    }
    
    container.innerHTML = html;
}

async function changeCalendarMonth(delta) {
    calendarState.currentDate.setMonth(calendarState.currentDate.getMonth() + delta);
    // Clear stats cache for the new month to ensure fresh data
    calendarState.dailyStats = {};
    await fetchOrderStatsForMonth();
    renderCalendar();
}

function goToToday() {
    calendarState.currentDate = new Date();
    // Clear stats and fetch fresh data for today
    calendarState.dailyStats = {};
    fetchOrderStatsForMonth().then(() => renderCalendar());
}

async function selectCalendarDate(dateStr) {
    calendarState.selectedDate = dateStr;
    
    // Update visual selection
    document.querySelectorAll('.calendar-day').forEach(el => el.classList.remove('selected'));
    const selectedEl = document.querySelector(`.calendar-day[data-date="${dateStr}"]`);
    if (selectedEl) selectedEl.classList.add('selected');
    
    // Show workers for this date
    await loadWorkersForDate(dateStr);
}

async function loadWorkersForDate(dateStr) {
    showLoading('Loading workers...');
    
    try {
        const response = await fetch(`${LOCAL_API}/dates/${dateStr}/workers`);
        const workers = await response.json();
        
        console.log(`Calendar: Loaded ${workers.length} workers for ${dateStr}`, workers.slice(0, 3));
        
        calendarState.workersForDate = workers;
        calendarState.filteredWorkers = workers;
        
        renderWorkersList();
        
        // Show the workers section
        const section = document.getElementById('dateWorkersSection');
        if (section) section.style.display = 'block';
        
        // Update title
        const title = document.getElementById('selectedDateTitle');
        if (title) {
            const dateObj = new Date(dateStr + 'T00:00:00');
            title.textContent = `Workers on ${dateObj.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })} (${workers.length})`;
        }
        
        showToast(`Loaded ${workers.length} workers`, 'success');
    } catch (error) {
        showToast('Failed to load workers', 'error');
        console.error(error);
    } finally {
        hideLoading();
    }
}

function renderWorkersList() {
    const container = document.getElementById('calendarWorkersList');
    if (!container) return;
    
    if (calendarState.filteredWorkers.length === 0) {
        container.innerHTML = '<p style="color: #666; text-align: center; padding: 40px;">No workers found for this date.</p>';
        return;
    }
    
    let html = '';
    calendarState.filteredWorkers.forEach(worker => {
        const locationsHtml = worker.locations.map(loc => 
            `<span class="location-tag">${loc}</span>`
        ).join('');
        
        const shiftsHtml = worker.shifts.map(shift => 
            `<div style="margin-bottom: 4px;">${shift.job_title} (${shift.hours.toFixed(2)}h)</div>`
        ).join('');
        
        html += `
            <div class="worker-card" onclick="selectWorkerForTips('${worker.name.replace(/'/g, "\\'")}')">
                <div class="worker-name">${worker.name}</div>
                <div class="worker-locations">${locationsHtml}</div>
                <div class="worker-shifts">${shiftsHtml}</div>
                <div class="worker-hours">Total: ${worker.total_hours.toFixed(2)} hours</div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

function filterCalendarWorkers() {
    const filter = document.getElementById('calendarWorkerFilter')?.value.toLowerCase() || '';
    
    if (!filter) {
        calendarState.filteredWorkers = calendarState.workersForDate;
    } else {
        calendarState.filteredWorkers = calendarState.workersForDate.filter(w => 
            w.name.toLowerCase().includes(filter) ||
            w.locations.some(l => l.toLowerCase().includes(filter)) ||
            w.shifts.some(s => s.job_title.toLowerCase().includes(filter))
        );
    }
    
    renderWorkersList();
}

function selectWorkerForTips(workerName) {
    // Navigate to server tips page with this worker and date pre-selected
    const dateStr = calendarState.selectedDate;
    
    // Build URL with params
    const params = new URLSearchParams();
    params.set('business_date', dateStr);
    params.set('worker', workerName);
    
    // Update URL hash with params
    window.location.hash = `server-tips?${params.toString()}`;
    
    // Apply params immediately (since we're already on the page or navigating)
    setTimeout(() => {
        applyServerTipsParams({ business_date: dateStr, worker: workerName });
        updateServerTipsWorkersForDate();
    }, 100);
    
    // Auto-fetch the data after dropdown is populated
    setTimeout(() => fetchServerTipsFromToast(), 600);
}

function quickAssignTipsFromCalendar() {
    // Navigate to server tips with the selected date
    const dateStr = calendarState.selectedDate;
    
    const dateInput = document.getElementById('serverTipsDate');
    if (dateInput) dateInput.value = dateStr;
    
    showPage(null, 'server-tips');
}

// =====================
// SERVER TIPS FUNCTIONS
// =====================
let serverCashCollectedForFormula = null;
let serverOrdersTaxForSummary = 0;
let serverOrdersGratuityFeesForSummary = 0;

function updateServerCategorySummaryExtras() {
    const netSales = parseFloat(document.getElementById('categoryTotalSales')?.textContent || '0') || 0;
    const tax = Number(serverOrdersTaxForSummary || 0);
    const gratuityFees = Number(serverOrdersGratuityFeesForSummary || 0);
    const nonCashTips = parseFloat(document.getElementById('serverCreditTips')?.value || '0') || 0;
    const grossSales = netSales + tax;
    const totalAmount = grossSales + gratuityFees + nonCashTips;

    const taxEl = document.getElementById('categoryTaxTotal');
    const grossEl = document.getElementById('categoryGrossSalesTotal');
    const gratuityEl = document.getElementById('categoryGratuityFeesTotal');
    const nonCashEl = document.getElementById('categoryNonCashTipsTotal');
    const totalAmountEl = document.getElementById('categoryTotalAmount');
    if (taxEl) taxEl.textContent = tax.toFixed(2);
    if (grossEl) grossEl.textContent = grossSales.toFixed(2);
    if (gratuityEl) gratuityEl.textContent = gratuityFees.toFixed(2);
    if (nonCashEl) nonCashEl.textContent = nonCashTips.toFixed(2);
    if (totalAmountEl) totalAmountEl.textContent = totalAmount.toFixed(2);
}

function renderServerShiftOverrideStatus(overrideData) {
    const select = document.getElementById('serverShiftOverrideBucket');
    const status = document.getElementById('serverShiftOverrideStatus');
    if (!select || !status) return;

    if (overrideData && overrideData.bucket) {
        select.value = overrideData.bucket;
        const bucketName = BUCKETS.find(b => b.id === overrideData.bucket)?.name || overrideData.bucket;
        status.textContent = `Active override: ${bucketName} (applied to this worker/date)`;
    } else {
        select.value = '';
        status.textContent = 'No override active.';
    }
}

async function saveServerShiftOverride() {
    const workerSelect = document.getElementById('serverTipsWorker');
    const selectedValue = workerSelect?.value;
    const selectedOption = workerSelect?.querySelector(`sl-option[value="${selectedValue}"]`);
    const worker = selectedOption?.getAttribute('data-worker-name') || selectedValue;
    const date = document.getElementById('serverTipsDate')?.value;
    const bucket = document.getElementById('serverShiftOverrideBucket')?.value;

    if (!worker || !date || !bucket) {
        showToast('Select worker, date, and override bucket', 'warning');
        return;
    }

    showLoading('Saving shift override...');
    try {
        const resp = await fetch(`${LOCAL_API}/server-shift-override`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ worker, date, bucket })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to save override');
        renderServerShiftOverrideStatus(data.override || null);
        showToast('Shift override saved', 'success');

        const bucketSelect = document.getElementById('serverTipsBucket');
        if (bucketSelect) bucketSelect.value = bucket;
        await fetchServerTipsFromToast();
    } catch (e) {
        showToast(e.message || 'Failed to save override', 'error');
    } finally {
        hideLoading();
    }
}

async function clearServerShiftOverride() {
    const workerSelect = document.getElementById('serverTipsWorker');
    const selectedValue = workerSelect?.value;
    const selectedOption = workerSelect?.querySelector(`sl-option[value="${selectedValue}"]`);
    const worker = selectedOption?.getAttribute('data-worker-name') || selectedValue;
    const date = document.getElementById('serverTipsDate')?.value;

    if (!worker || !date) {
        showToast('Select worker and date', 'warning');
        return;
    }

    showLoading('Clearing shift override...');
    try {
        const params = new URLSearchParams({ worker, date });
        const resp = await fetch(`${LOCAL_API}/server-shift-override?${params}`, { method: 'DELETE' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to clear override');
        renderServerShiftOverrideStatus(null);
        showToast('Shift override cleared', 'success');
        await fetchServerTipsFromToast();
    } catch (e) {
        showToast(e.message || 'Failed to clear override', 'error');
    } finally {
        hideLoading();
    }
}

async function fetchServerTipsFromToast() {
    const workerSelect = document.getElementById('serverTipsWorker');
    // Find selected option by matching value (Shoelace stores value, not selected attribute)
    const selectedValue = workerSelect?.value;
    const selectedOption = workerSelect?.querySelector(`sl-option[value="${selectedValue}"]`);
    const worker = selectedOption?.getAttribute('data-worker-name') || selectedValue;
    const date = document.getElementById('serverTipsDate')?.value;
    const bucket = document.getElementById('serverTipsBucket')?.value;
    
    if (!worker || !date) {
        showToast('Please select worker and date', 'warning');
        return;
    }
    
    // Update summary worker name
    const summaryWorker = document.getElementById('summaryWorker');
    if (summaryWorker) summaryWorker.textContent = worker;
    const summaryBucket = document.getElementById('summaryBucket');
    if (summaryBucket) summaryBucket.textContent = bucket || '-';
    updateServerSplitIndicator(0);
    serverCashCollectedForFormula = null;
    serverOrdersTaxForSummary = 0;
    serverOrdersGratuityFeesForSummary = 0;
    
    showLoading('Fetching data from Toast...');
    
    try {
        // Fetch from API (now includes suggested buckets)
        const params = new URLSearchParams({ worker, date, bucket });
        const response = await fetch(`${LOCAL_API}/server-tips?${params}`);
        const data = await response.json();
        renderServerShiftOverrideStatus(data.shift_bucket_override || null);
        if (data.calculated_tips && data.calculated_tips.cash_collected !== undefined && data.calculated_tips.cash_collected !== null) {
            serverCashCollectedForFormula = parseFloat(data.calculated_tips.cash_collected || 0);
        }
        
        // Get bucket IDs for status fetching
        const bucketIds = data.suggested_buckets?.map(b => b.id) || [];
        
        // Fetch status data first so we can use it for both displays
        let statusData = {};
        if (bucketIds.length > 0) {
            try {
                const statusParams = new URLSearchParams({ worker, date, buckets: bucketIds.join(',') });
                const statusResponse = await fetch(`${LOCAL_API}/server/bucket-status?${statusParams}`);
                if (statusResponse.ok) {
                    statusData = await statusResponse.json();
                }
            } catch (e) {
                console.warn('Failed to fetch bucket status:', e);
            }
        }
        
        // Display suggested buckets based on shifts with status
        if (data.suggested_buckets && data.suggested_buckets.length > 0) {
            displaySuggestedBuckets(data.suggested_buckets);
            // Apply status styling to suggested bucket buttons
            applyBucketStatusToButtons(bucketIds, statusData);
        } else {
            displaySuggestedBuckets([]);
        }
        
        // Populate form with data
        let tipsData = null;
        
        const hasOverride = !!data.existing_record?.is_override;

        if (data.existing_record) {
            // Use existing saved data
            tipsData = data.existing_record;
            showToast('Existing tips loaded', 'success');
        } else if (data.calculated_tips) {
            // Use calculated tips from Toast orders
            tipsData = data.calculated_tips;
            showToast('Tips calculated from Toast orders', 'success');
        }
        
        if (tipsData) {
            // Use declared cash tips from Toast time entries if available, otherwise use calculated from orders
            const cashTips = (tipsData.declared_cash_tips !== undefined && tipsData.declared_cash_tips !== null) 
                ? tipsData.declared_cash_tips 
                : (tipsData.cash_tips || 0);
            document.getElementById('serverCashTips').value = cashTips.toFixed(2);
            document.getElementById('serverCreditTips').value = (tipsData.non_cash_tips || 0).toFixed(2);
            document.getElementById('serverGratuity').value = (tipsData.gratuity || 0).toFixed(2);
            document.getElementById('serverNetSales').value = (tipsData.net_sales || 0).toFixed(2);

            if (hasOverride) {
                document.getElementById('serverBarTips').value = (tipsData.bar_tips || 0).toFixed(2);
                document.getElementById('serverBusserTips').value = (tipsData.busser_tips || 0).toFixed(2);
                document.getElementById('serverExpoTips').value = (tipsData.expo_tips || 0).toFixed(2);
                document.getElementById('serverRunnerTips').value = (tipsData.runner_tips || 0).toFixed(2);
            }
            
            // Display breakdown by bucket if available (with status data for coloring)
            if (tipsData.tips_by_bucket && Object.keys(tipsData.tips_by_bucket).length > 0) {
                // Pass declared cash tips so bucket display matches main figures
                const declaredCash = tipsData.declared_cash_tips;
                displayTipsByBucket(tipsData.tips_by_bucket, statusData, declaredCash);
            }
        } else {
            showToast('No tips data found for this worker/date', 'warning');
        }
        
        if (!hasOverride) {
            document.getElementById('serverBarTips').value = "0.00";
            document.getElementById('serverBusserTips').value = "0.00";
            document.getElementById('serverExpoTips').value = "0.00";
            document.getElementById('serverRunnerTips').value = "0.00";
        }
        
        // Show form and load category breakdown
        document.getElementById('serverTipsForm').style.display = 'block';
        
        // Load category breakdown and update calculations
        await loadCategoryBreakdown(worker, date, bucket, { preserveManualValues: hasOverride });
        updateServerTipsCalculations();
        
        // Update URL with current parameters for sharing/bookmarking
        updateUrlWithParams('server-tips', { 
            business_date: date, 
            worker: worker,
            bucket: bucket 
        });
        
    } catch (error) {
        showToast('Failed to fetch data', 'error');
        console.error(error);
    } finally {
        hideLoading();
    }
    
    // Load orders for this worker/date/bucket
    await loadServerOrders(worker, date, bucket);
}

// Load and display orders for a server on a specific date
async function loadServerOrders(worker, date, bucket) {
    const ordersSection = document.getElementById('serverOrdersSection');
    const ordersBody = document.getElementById('serverOrdersBody');
    const ordersCount = document.getElementById('serverOrdersCount');
    
    if (!ordersSection || !ordersBody) return;
    
    // Reset display
    ordersSection.style.display = 'none';
    ordersBody.innerHTML = '<tr><td colspan="11" style="padding: 20px; text-align: center; color: #666;"><sl-spinner></sl-spinner> Loading orders...</td></tr>';
    const subtotalCell = document.getElementById('serverOrdersSubtotal');
    const taxCell = document.getElementById('serverOrdersTax');
    const nonCashTipsCell = document.getElementById('serverOrdersNonCashTips');
    const gratuityFeesCell = document.getElementById('serverOrdersGratuityFees');
    const totalCell = document.getElementById('serverOrdersTotal');
    const itemCountCell = document.getElementById('serverOrdersItemCount');
    if (subtotalCell) subtotalCell.textContent = '$0.00';
    if (taxCell) taxCell.textContent = '$0.00';
    if (nonCashTipsCell) nonCashTipsCell.textContent = '$0.00';
    if (gratuityFeesCell) gratuityFeesCell.textContent = '$0.00';
    if (totalCell) totalCell.textContent = '$0.00';
    if (itemCountCell) itemCountCell.textContent = '0';
    
    try {
        const params = new URLSearchParams({ worker, date });
        if (bucket) {
            params.append('bucket', bucket);
        }
        const response = await fetch(`${LOCAL_API}/server-tips/orders?${params}`);
        
        if (!response.ok) {
            const errorData = await response.json();
            ordersBody.innerHTML = `<tr><td colspan="11" style="padding: 20px; text-align: center; color: #666;">${errorData.error || 'No order data available'}</td></tr>`;
            if (ordersCount) ordersCount.textContent = '0 orders';
            serverOrdersTaxForSummary = 0;
            serverOrdersGratuityFeesForSummary = 0;
            updateServerCategorySummaryExtras();
            return;
        }
        
        const data = await response.json();
        
        if (!data.orders || data.orders.length === 0) {
            ordersBody.innerHTML = '<tr><td colspan="11" style="padding: 20px; text-align: center; color: #666;">No orders found for this worker on this date</td></tr>';
            ordersSection.style.display = 'block';
            if (ordersCount) ordersCount.textContent = '0 orders';
            if (gratuityFeesCell) gratuityFeesCell.textContent = '$0.00';
            serverOrdersTaxForSummary = 0;
            serverOrdersGratuityFeesForSummary = 0;
            updateServerCategorySummaryExtras();
            return;
        }
        
        // Build orders table
        let html = '';
        let totalSubtotal = 0;
        let totalTax = 0;
        let totalNonCashTips = 0;
        let totalGratuityFees = 0;
        let totalAmount = 0;
        let totalItems = 0;
        
        data.orders.forEach(order => {
            const orderTime = order.paid_date ? new Date(order.paid_date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '-';
            const orderNumber = order.order_number || order.order_guid?.slice(0, 8) || 'Unknown';
            
            // Each order can have multiple checks
            order.checks.forEach((check, checkIndex) => {
                totalSubtotal += check.subtotal || 0;
                totalTax += check.tax || 0;
                totalNonCashTips += check.non_cash_tips || 0;
                totalGratuityFees += check.gratuity_fees || 0;
                totalAmount += check.total || 0;
                totalItems += check.item_count || 0;
                
                html += `
                    <tr style="border-bottom: 1px solid #eee;">
                        ${checkIndex === 0 ? `<td rowspan="${order.checks.length}" style="padding: 10px; font-weight: 500; vertical-align: top;">${escapeHtml(orderNumber)}</td>` : ''}
                        <td style="padding: 10px; vertical-align: top;">${escapeHtml(check.check_number || check.check_guid?.slice(0, 8) || '-')}</td>
                        ${checkIndex === 0 ? `<td rowspan="${order.checks.length}" style="padding: 10px; vertical-align: top;">${orderTime}</td>` : ''}
                        <td style="padding: 10px; text-align: right;">$${(check.subtotal || 0).toFixed(2)}</td>
                        <td style="padding: 10px; text-align: right;">$${(check.tax || 0).toFixed(2)}</td>
                        <td style="padding: 10px; text-align: right;">$${(check.non_cash_tips || 0).toFixed(2)}</td>
                        <td style="padding: 10px; text-align: right;">$${(check.gratuity_fees || 0).toFixed(2)}</td>
                        <td style="padding: 10px; text-align: right; font-weight: 600;">$${(check.total || 0).toFixed(2)}</td>
                        <td style="padding: 10px; text-align: center;">${check.item_count || 0}</td>
                        <td style="padding: 10px; text-align: center;">
                            <span id="split-badge-${check.check_guid}" class="split-badge" style="display: none;">
                                <sl-badge variant="warning" pill>Split</sl-badge>
                            </span>
                            <span id="split-workers-${check.check_guid}" class="split-workers" style="font-size: 11px; color: #666;"></span>
                        </td>
                        <td style="padding: 10px; text-align: center;">
                            <sl-button size="small" variant="primary" onclick="openCheckAssignmentDialog('${order.order_guid}', '${check.check_guid}', '${order.order_number || ''}', '${check.check_number || ''}', ${check.total || 0})">
                                <sl-icon slot="prefix" name="people"></sl-icon>
                                Split
                            </sl-button>
                        </td>
                    </tr>
                `;
            });
        });
        
        ordersBody.innerHTML = html;
        
        // Update totals
        document.getElementById('serverOrdersSubtotal').textContent = `$${totalSubtotal.toFixed(2)}`;
        document.getElementById('serverOrdersTax').textContent = `$${totalTax.toFixed(2)}`;
        document.getElementById('serverOrdersNonCashTips').textContent = `$${totalNonCashTips.toFixed(2)}`;
        document.getElementById('serverOrdersGratuityFees').textContent = `$${totalGratuityFees.toFixed(2)}`;
        document.getElementById('serverOrdersTotal').textContent = `$${totalAmount.toFixed(2)}`;
        document.getElementById('serverOrdersItemCount').textContent = totalItems;
        serverOrdersTaxForSummary = totalTax;
        serverOrdersGratuityFeesForSummary = totalGratuityFees;
        updateServerCategorySummaryExtras();
        
        // Update count badge
        if (ordersCount) {
            ordersCount.textContent = `${data.order_count} order${data.order_count !== 1 ? 's' : ''}`;
        }
        
        // Show the section
        ordersSection.style.display = 'block';
        
        // Load existing check assignments
        await loadCheckAssignments(worker, date);
        
    } catch (error) {
        console.error('Error loading server orders:', error);
        ordersBody.innerHTML = `<tr><td colspan="11" style="padding: 20px; text-align: center; color: #d32f2f;">Error loading orders: ${escapeHtml(error.message)}</td></tr>`;
        ordersSection.style.display = 'block';
        const nonCashTipsCell = document.getElementById('serverOrdersNonCashTips');
        const gratuityFeesCell = document.getElementById('serverOrdersGratuityFees');
        if (nonCashTipsCell) nonCashTipsCell.textContent = '$0.00';
        if (gratuityFeesCell) gratuityFeesCell.textContent = '$0.00';
        serverOrdersTaxForSummary = 0;
        serverOrdersGratuityFeesForSummary = 0;
        updateServerCategorySummaryExtras();
    }
}

// Store current check being edited
let currentCheckAssignment = null;

// Load check assignments for a worker/date
async function loadCheckAssignments(worker, date) {
    try {
        const params = new URLSearchParams({ worker, date });
        const response = await fetch(`${LOCAL_API}/check-assignments?${params}`);
        
        if (!response.ok) return;
        
        const data = await response.json();
        
        // Update UI for each assignment
        let visibleSplitCount = 0;
        data.assignments.forEach(assignment => {
            const badge = document.getElementById(`split-badge-${assignment.check_guid}`);
            const workers = document.getElementById(`split-workers-${assignment.check_guid}`);
            
            if (badge && workers) {
                const assignedWorkers = assignment.assigned_workers || [];
                if (assignedWorkers.length > 1 || (assignedWorkers.length === 1 && assignedWorkers[0].worker_name !== worker)) {
                    badge.style.display = 'inline';
                    const workerNames = assignedWorkers.map(aw => aw.worker_name.split(' ')[0]).join(', ');
                    workers.textContent = workerNames;
                    visibleSplitCount += 1;
                }
            }
        });
        
        // Update split count
        document.getElementById('splitCheckCount').textContent = visibleSplitCount;
        updateServerSplitIndicator(visibleSplitCount);
        
    } catch (error) {
        console.warn('Error loading check assignments:', error);
        updateServerSplitIndicator(0);
    }
}

function updateServerSplitIndicator(splitCount) {
    const badge = document.getElementById('serverMainFiguresSplitBadge');
    if (!badge) return;
    badge.style.display = splitCount > 0 ? 'inline-flex' : 'none';
}

// Open check assignment dialog
async function openCheckAssignmentDialog(orderGuid, checkGuid, orderNum, checkNum, total) {
    currentCheckAssignment = {
        order_guid: orderGuid,
        check_guid: checkGuid,
        order_number: orderNum,
        check_number: checkNum,
        total: total
    };
    
    document.getElementById('assignDialogOrderNum').textContent = orderNum || '-';
    document.getElementById('assignDialogCheckNum').textContent = checkNum || '-';
    document.getElementById('assignDialogTotal').textContent = total.toFixed(2);
    
    // Get current date to fetch workers who worked that day
    const dateInput = document.getElementById('serverTipsDate');
    const date = dateInput?.value;
    const currentWorker = document.getElementById('serverTipsWorker')?.value;
    
    // Populate worker checkboxes - fetch workers who worked on this date
    const container = document.getElementById('checkWorkerAssignments');
    container.innerHTML = '<div style="padding: 12px; text-align: center;"><sl-spinner></sl-spinner> Loading workers...</div>';
    
    document.getElementById('checkAssignmentDialog').show();
    
    try {
        let workersList = [];
        
        if (date) {
            // Fetch workers who worked on this date
            const response = await fetch(`${LOCAL_API}/dates/${date}/workers`);
            if (response.ok) {
                const data = await response.json();
                workersList = data.workers || data || [];
            }
        }
        
        // Fallback to WORKERS if API fails
        if (workersList.length === 0) {
            workersList = WORKERS.map(w => ({ name: w }));
        }
        
        container.innerHTML = '';
        
        if (workersList.length === 0) {
            container.innerHTML = '<div style="padding: 12px; color: #666;">No workers found for this date</div>';
            return;
        }
        
        // Get current worker to pre-check
        const currentWorkerSelect = document.getElementById('serverTipsWorker');
        const currentWorkerName = currentWorkerSelect?.selectedOptions[0]?.getAttribute('data-worker-name') || currentWorkerSelect?.value;
        
        // Filter to only show workers with 'Server' or 'Bar' in their job title
        const eligibleWorkers = workersList.filter(workerData => {
            const jobTitle = workerData.job_title || '';
            return jobTitle.toLowerCase().includes('server') || 
                   jobTitle.toLowerCase().includes('bar');
        });
        
        // If no eligible workers found, show all (fallback)
        const workersToShow = eligibleWorkers.length > 0 ? eligibleWorkers : workersList;
        
        workersToShow.forEach(workerData => {
            const workerName = workerData.name || workerData.worker_name || workerData;
            if (!workerName) return;
            
            // Pre-check the current worker
            const isChecked = workerName === currentWorkerName ? 'checked' : '';
            
            const div = document.createElement('div');
            div.style.cssText = 'display: flex; align-items: center; gap: 8px; padding: 6px; border-bottom: 1px solid #f0f0f0;';
            div.innerHTML = `
                <sl-checkbox class="check-worker-checkbox" data-worker="${escapeHtml(workerName)}" value="${escapeHtml(workerName)}" ${isChecked}>
                    ${escapeHtml(workerName)}
                </sl-checkbox>
            `;
            container.appendChild(div);
        });
        
        // Show message if workers were filtered
        if (eligibleWorkers.length > 0 && eligibleWorkers.length < workersList.length) {
            const filterMsg = document.createElement('div');
            filterMsg.style.cssText = 'padding: 8px; font-size: 12px; color: #666; font-style: italic; border-top: 1px solid #eee;';
            filterMsg.textContent = `Showing ${eligibleWorkers.length} of ${workersList.length} workers (Servers and Bar staff only)`;
            container.appendChild(filterMsg);
        }
        
    } catch (error) {
        console.error('Error loading workers:', error);
        container.innerHTML = '<div style="padding: 12px; color: #d32f2f;">Error loading workers</div>';
    }
}

// Save check assignment
async function saveCheckAssignment() {
    if (!currentCheckAssignment) return;
    
    const workerSelect = document.getElementById('serverTipsWorker');
    const dateInput = document.getElementById('serverTipsDate');
    const bucketSelect = document.getElementById('serverTipsBucket');
    
    const primaryWorker = (() => {
        const val = workerSelect?.value;
        const opt = workerSelect?.querySelector(`sl-option[value="${val}"]`);
        return opt?.getAttribute('data-worker-name') || val;
    })();
    
    const date = dateInput?.value;
    const bucket = bucketSelect?.value;
    
    if (!primaryWorker || !date) {
        showToast('Worker and date required', 'error');
        return;
    }
    
    // Get selected workers
    const checkboxes = document.querySelectorAll('.check-worker-checkbox');
    const selectedWorkers = [];
    let primaryWorkerIncluded = false;
    
    checkboxes.forEach(cb => {
        if (cb.checked) {
            const workerName = cb.getAttribute('data-worker');
            selectedWorkers.push({
                worker_name: workerName,
                split_percentage: 100 / checkboxes.length  // Will be adjusted below
            });
            if (workerName === primaryWorker) {
                primaryWorkerIncluded = true;
            }
        }
    });
    
    // Always include the primary worker if not already selected
    if (!primaryWorkerIncluded) {
        selectedWorkers.push({
            worker_name: primaryWorker,
            split_percentage: 100 / (checkboxes.length + 1)  // Will be adjusted below
        });
    }
    
    if (selectedWorkers.length === 0) {
        showToast('Select at least one worker', 'warning');
        return;
    }
    
    // Adjust percentages for equal split among all selected workers
    const equalPct = 100 / selectedWorkers.length;
    selectedWorkers.forEach(sw => sw.split_percentage = equalPct);
    
    try {
        const response = await fetch(`${LOCAL_API}/check-assignments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                worker_name: primaryWorker,
                business_date: date,
                order_guid: currentCheckAssignment.order_guid,
                check_guid: currentCheckAssignment.check_guid,
                order_number: currentCheckAssignment.order_number,
                check_number: currentCheckAssignment.check_number,
                total_amount: currentCheckAssignment.total,
                subtotal: currentCheckAssignment.total * 0.9,  // Approximate
                tax_amount: currentCheckAssignment.total * 0.1,
                assigned_workers: selectedWorkers,
                split_type: document.getElementById('checkSplitType')?.value || 'equal',
                bucket: bucket
            })
        });
        
        if (response.ok) {
            showToast('Check assignment saved', 'success');
            document.getElementById('checkAssignmentDialog').hide();
            await fetchServerTipsFromToast();
        } else {
            const error = await response.json();
            showToast(error.error || 'Failed to save assignment', 'error');
        }
    } catch (error) {
        console.error('Error saving check assignment:', error);
        showToast('Failed to save assignment', 'error');
    }
}

// Clear all check assignments for current worker/date
async function clearAllCheckAssignments() {
    const workerSelect = document.getElementById('serverTipsWorker');
    const dateInput = document.getElementById('serverTipsDate');
    
    const worker = (() => {
        const val = workerSelect?.value;
        const opt = workerSelect?.querySelector(`sl-option[value="${val}"]`);
        return opt?.getAttribute('data-worker-name') || val;
    })();
    const date = dateInput?.value;
    
    if (!worker || !date) {
        showToast('Worker and date required', 'warning');
        return;
    }
    
    if (!confirm('Clear all check assignments for this worker/date?')) {
        return;
    }
    
    try {
        const params = new URLSearchParams({ worker, date });
        const response = await fetch(`${LOCAL_API}/check-assignments?${params}`);
        const data = await response.json();
        
        // Delete each assignment
        for (const assignment of data.assignments) {
            await fetch(`${LOCAL_API}/check-assignments?check_guid=${assignment.check_guid}&worker_name=${worker}&business_date=${date}`, {
                method: 'DELETE'
            });
        }
        
        showToast('All assignments cleared', 'success');
        
        // Clear UI
        document.querySelectorAll('.split-badge').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.split-workers').forEach(el => el.textContent = '');
        document.getElementById('splitCheckCount').textContent = '0';
        updateServerSplitIndicator(0);
        await fetchServerTipsFromToast();
        
    } catch (error) {
        console.error('Error clearing assignments:', error);
        showToast('Failed to clear assignments', 'error');
    }
}

// Display suggested buckets based on worker's shifts
function displaySuggestedBuckets(buckets) {
    const container = document.getElementById('suggestedBuckets');
    if (!container) return;
    
    if (buckets.length === 0) {
        container.innerHTML = '<p style="color: #666; font-style: italic;">No shifts found for this worker on the selected date. Please select a location manually.</p>';
        return;
    }
    
    let html = '<div style="display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px;">';
    
    buckets.forEach(b => {
        html += `
            <sl-button class="bucket-suggestion bucket-status-unpushed" data-bucket="${b.id}" onclick="selectSuggestedBucket('${b.id}')" 
                style="margin: 4px;" pill>
                <sl-icon slot="prefix" name="geo-alt"></sl-icon>
                ${b.name} <small>(${b.job_title}, ${b.hours.toFixed(2)}h)</small>
            </sl-button>
        `;
    });
    
    html += '</div>';
    html += '<p style="font-size: 13px; color: #666; margin: 0;">Click a location above to auto-select it, or choose manually from the dropdown.</p>';
    
    container.innerHTML = html;
}

// Select a suggested bucket
function selectSuggestedBucket(bucketId) {
    const select = document.getElementById('serverTipsBucket');
    if (select) {
        select.value = bucketId;
        showToast(`Selected: ${bucketId}`, 'success');
        const workerSelect = document.getElementById('serverTipsWorker');
        const selectedValue = workerSelect?.value;
        const selectedOption = workerSelect?.querySelector(`sl-option[value="${selectedValue}"]`);
        const worker = selectedOption?.getAttribute('data-worker-name') || selectedValue;
        const date = document.getElementById('serverTipsDate')?.value;
        if (worker && date) {
            fetchServerTipsFromToast();
        }
    }
}

// Display tips breakdown by bucket (location)
function displayTipsByBucket(tipsByBucket, statusData = {}, declaredCashTips = null) {
    const container = document.getElementById('suggestedBuckets');
    if (!container) return;
    
    let html = '<div style="background: #f5f5f5; border-radius: 8px; padding: 16px; margin-bottom: 16px;">';
    html += '<h4 style="margin: 0 0 12px 0; font-size: 14px; color: #333;">Tips by Location:</h4>';
    html += '<div style="display: grid; gap: 8px;">';
    
    for (const [bucketId, tips] of Object.entries(tipsByBucket)) {
        const bucketName = BUCKETS.find(b => b.id === bucketId)?.name || bucketId;
        // Use declared cash tips from time entries if available, otherwise fall back to calculated from orders
        const cashTips = (declaredCashTips !== null && declaredCashTips !== undefined) 
            ? parseFloat(declaredCashTips).toFixed(2)
            : parseFloat(tips.cash_tips || 0).toFixed(2);
        const creditTips = parseFloat(tips.non_cash_tips || 0).toFixed(2);
        const netSales = parseFloat(tips.net_sales || 0).toFixed(2);
        const totalTips = (parseFloat(cashTips) + parseFloat(creditTips)).toFixed(2);
        
        // Determine status color
        const status = statusData[bucketId]?.status || 'unpushed';
        let borderColor = '#999'; // unpushed - grey
        let bgColor = '#f8f8f8';
        let statusLabel = '';
        let totalColor = '#666'; // grey for unpushed
        
        if (status === 'pushed') {
            borderColor = '#e65100'; // orange
            bgColor = '#fff3e0';
            totalColor = '#e65100'; // orange
            statusLabel = ' <span style="color: #e65100; font-size: 11px; font-weight: 600;">(PUSHED)</span>';
        } else if (status === 'committed') {
            borderColor = '#2e7d32'; // green
            bgColor = '#e8f5e9';
            totalColor = '#2e7d32'; // green
            statusLabel = ' <span style="color: #2e7d32; font-size: 11px; font-weight: 600;">(COMMITTED)</span>';
        }
        
        html += `
            <div style="background: white; border-radius: 6px; padding: 12px; border-left: 4px solid ${borderColor};" data-bucket-card="${bucketId}">
                <div style="font-weight: 600; color: #333; margin-bottom: 8px;">${bucketName}${statusLabel}</div>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; font-size: 12px;">
                    <div>
                        <span style="color: #666;">Cash Tips:</span>
                        <span style="font-weight: 600;">$${cashTips}</span>
                    </div>
                    <div>
                        <span style="color: #666;">Credit Tips:</span>
                        <span style="font-weight: 600;">$${creditTips}</span>
                    </div>
                    <div>
                        <span style="color: #666;">Net Sales:</span>
                        <span style="font-weight: 600;">$${netSales}</span>
                    </div>
                </div>
                <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #eee;">
                    <span style="color: #666;">Total Tips:</span>
                    <span style="font-weight: 700; color: ${totalColor};">$${totalTips}</span>
                </div>
            </div>
        `;
    }
    
    html += '</div>';
    html += '</div>';
    
    container.innerHTML = html;
}

async function saveServerTips() {
    showLoading('Saving server tips...');
    
    const data = {
        worker: (() => {
            const ws = document.getElementById('serverTipsWorker');
            const val = ws?.value;
            const opt = ws?.querySelector(`sl-option[value="${val}"]`);
            return opt?.getAttribute('data-worker-name') || val;
        })(),
        date: document.getElementById('serverTipsDate')?.value,
        bucket: document.getElementById('serverTipsBucket')?.value,
        cash_tips: parseFloat(document.getElementById('serverCashTips')?.value || 0),
        credit_tips: parseFloat(document.getElementById('serverCreditTips')?.value || 0),
        gratuity: parseFloat(document.getElementById('serverGratuity')?.value || 0),
        net_sales: parseFloat(document.getElementById('serverNetSales')?.value || 0),
        bar_tips: parseFloat(document.getElementById('serverBarTips')?.value || 0),
        busser_tips: parseFloat(document.getElementById('serverBusserTips')?.value || 0),
        expo_tips: parseFloat(document.getElementById('serverExpoTips')?.value || 0),
        runner_tips: parseFloat(document.getElementById('serverRunnerTips')?.value || 0)
    };
    
    try {
        const response = await fetch(`${LOCAL_API}/server-tips`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            showToast('Server tips saved', 'success');
        } else {
            throw new Error('Failed to save');
        }
    } catch (error) {
        showToast('Failed to save: ' + error.message, 'error');
    } finally {
        hideLoading();
    }
}

async function pushServerTipsToPayouts() {
    const worker = (() => {
        const ws = document.getElementById('serverTipsWorker');
        const val = ws?.value;
        const opt = ws?.querySelector(`sl-option[value="${val}"]`);
        return opt?.getAttribute('data-worker-name') || val;
    })();
    const date = document.getElementById('serverTipsDate')?.value;
    const bucket = document.getElementById('serverTipsBucket')?.value;
    
    if (!worker || !date || !bucket) {
        showToast('Please select worker, date, and bucket', 'warning');
        return;
    }
    
    if (!confirm('Push these tips to payouts for this date and bucket?')) return;
    
    showLoading('Pushing to payouts...');
    
    try {
        const data = {
            worker,
            date,
            bucket,
            bar_tips: parseFloat(document.getElementById('serverBarTips')?.value || 0),
            busser_tips: parseFloat(document.getElementById('serverBusserTips')?.value || 0),
            expo_tips: parseFloat(document.getElementById('serverExpoTips')?.value || 0),
            runner_tips: parseFloat(document.getElementById('serverRunnerTips')?.value || 0),
            cash_tips: parseFloat(document.getElementById('serverCashTips')?.value || 0),
            credit_tips: parseFloat(document.getElementById('serverCreditTips')?.value || 0),
            gratuity: parseFloat(document.getElementById('serverGratuity')?.value || 0),
            net_sales: parseFloat(document.getElementById('serverNetSales')?.value || 0)
        };
        
        const response = await fetch(`${LOCAL_API}/server-tips/push`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showToast(result.message || 'Tips pushed to payouts', 'success');
            // Refresh bucket status
            fetchServerTipsFromToast();
        } else {
            throw new Error(result.error || 'Failed to push');
        }
    } catch (error) {
        showToast('Failed to push: ' + error.message, 'error');
        console.error(error);
    } finally {
        hideLoading();
    }
}

async function undoServerTipsPayouts() {
    const worker = (() => {
        const ws = document.getElementById('serverTipsWorker');
        const val = ws?.value;
        const opt = ws?.querySelector(`sl-option[value="${val}"]`);
        return opt?.getAttribute('data-worker-name') || val;
    })();
    const date = document.getElementById('serverTipsDate')?.value;
    const bucket = document.getElementById('serverTipsBucket')?.value;
    
    if (!worker || !date || !bucket) {
        showToast('Please select worker, date, and bucket', 'warning');
        return;
    }
    
    if (!confirm('Undo unpaid payouts for this worker, date, and location?')) return;
    
    showLoading('Undoing payouts...');
    
    try {
        const response = await fetch(`${LOCAL_API}/server-tips/undo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ worker, date, bucket })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showToast(result.message || 'Payouts undone', 'success');
            // Refresh bucket status
            fetchServerTipsFromToast();
        } else {
            throw new Error(result.error || 'Failed to undo');
        }
    } catch (error) {
        showToast('Failed to undo: ' + error.message, 'error');
        console.error(error);
    } finally {
        hideLoading();
    }
}

// Real-time calculations for Server Tips
function updateServerTipsCalculations() {
    // Get input values
    const cashTips = parseFloat(document.getElementById('serverCashTips')?.value || 0);
    const creditTips = parseFloat(document.getElementById('serverCreditTips')?.value || 0);
    const gratuity = parseFloat(document.getElementById('serverGratuity')?.value || 0);
    const netSales = parseFloat(document.getElementById('serverNetSales')?.value || 0);
    
    const barTips = parseFloat(document.getElementById('serverBarTips')?.value || 0);
    const busserTips = parseFloat(document.getElementById('serverBusserTips')?.value || 0);
    const expoTips = parseFloat(document.getElementById('serverExpoTips')?.value || 0);
    const runnerTips = parseFloat(document.getElementById('serverRunnerTips')?.value || 0);
    
    // Calculate totals
    const totalPayoutTips = barTips + busserTips + expoTips + runnerTips;
    const totalTips = cashTips + creditTips + gratuity;
    const cashCollected = Number.isFinite(serverCashCollectedForFormula) && serverCashCollectedForFormula !== null
        ? serverCashCollectedForFormula
        : cashTips;
    
    // Owed calculations based on intermediate formula:
    // (gratuity + non-cash) - cash sales
    const formulaValue = (gratuity + creditTips) - cashCollected;
    const owedToServer = formulaValue > 0 ? formulaValue : 0;
    const owedToRestaurant = formulaValue < 0 ? Math.abs(formulaValue) : 0;
    // Keep "After Payout Tips" consistent with legacy behavior:
    // positive net: reduce by payout; negative net: increase restaurant owed by payout.
    const afterPayout = formulaValue >= 0
        ? (owedToServer - totalPayoutTips)
        : (owedToRestaurant + totalPayoutTips);
    
    // Gross tip percentage
    const grossTipPct = netSales > 0 ? ((totalTips / netSales) * 100).toFixed(2) : '0.00';
    
    // Update summary table
    document.getElementById('summaryTotalPayout').textContent = totalPayoutTips.toFixed(2);
    document.getElementById('summaryOwedServer').textContent = owedToServer.toFixed(2);
    document.getElementById('summaryOwedRestaurant').textContent = owedToRestaurant.toFixed(2);
    document.getElementById('summaryAfterPayout').textContent = afterPayout.toFixed(2);
    document.getElementById('summaryGrossTipPct').textContent = grossTipPct + '%';
    
    // Update intermediate totals
    const intermediateSection = document.getElementById('serverTipsIntermediateTotals');
    if (intermediateSection) {
        intermediateSection.style.display = 'block';
        document.getElementById('intermediateGratuity').textContent = gratuity.toFixed(2);
        document.getElementById('intermediateNonCash').textContent = creditTips.toFixed(2);
        document.getElementById('intermediateCashCollected').textContent = cashCollected.toFixed(2);
        document.getElementById('intermediateFormula').textContent = formulaValue.toFixed(2);
    }
    updateServerCategorySummaryExtras();
}

// Apply status styling to bucket buttons (used when status data is already fetched)
function applyBucketStatusToButtons(bucketIds, statusData) {
    if (!bucketIds || bucketIds.length === 0) return;
    
    // Small delay to ensure buttons are in DOM
    setTimeout(() => {
        bucketIds.forEach(bucketId => {
            const status = statusData[bucketId]?.status || 'unpushed';
            const buttons = document.querySelectorAll(`sl-button[data-bucket="${bucketId}"]`);
            buttons.forEach(btn => {
                // Remove old status classes
                btn.classList.remove('bucket-status-unpushed', 'bucket-status-pushed', 'bucket-status-committed');
                btn.classList.add(`bucket-status-${status}`);
                
                // Force style update by setting CSS custom properties
                if (status === 'pushed') {
                    btn.style.cssText = `--sl-color-primary-600: #e65100; --sl-color-primary-500: #ff9800; margin: 4px;`;
                    btn.setAttribute('variant', 'primary');
                } else if (status === 'committed') {
                    btn.style.cssText = `--sl-color-primary-600: #2e7d32; --sl-color-primary-500: #4caf50; margin: 4px;`;
                    btn.setAttribute('variant', 'primary');
                } else {
                    // Reset to default unpushed style (neutral)
                    btn.style.cssText = 'margin: 4px;';
                    btn.setAttribute('variant', 'default');
                }
            });
        });
    }, 100);
}

// Fetch bucket status (pushed/committed) for suggested buckets
async function fetchBucketStatus(worker, date, bucketIds) {
    if (!worker || !date || !bucketIds || bucketIds.length === 0) return;
    
    try {
        const params = new URLSearchParams({
            worker,
            date,
            buckets: bucketIds.join(',')
        });
        const response = await fetch(`${LOCAL_API}/server/bucket-status?${params}`);
        if (!response.ok) return;
        
        const statusData = await response.json();
        applyBucketStatusToButtons(bucketIds, statusData);
    } catch (e) {
        console.warn('Failed to fetch bucket status:', e);
    }
}

// Load category breakdown for server tips
async function loadCategoryBreakdown(worker, date, bucket, options = {}) {
    if (!worker || !date) return;
    
    try {
        const params = new URLSearchParams({ worker, date, bucket });
        const response = await fetch(`${LOCAL_API}/server-tips/breakdown?${params}`);
        if (!response.ok) return;
        
        const data = await response.json();
        
        // Show the category breakdown section
        const breakdownSection = document.getElementById('serverTipsCategoryBreakdown');
        if (breakdownSection) {
            breakdownSection.style.display = 'block';
        }
        
        // Populate category rows
        const tbody = document.getElementById('categoryBreakdownBody');
        if (!tbody) return;
        
        const categories = ['Food', 'Wine', 'Draft Beer', 'Liquor', 'NA Beverage', 'Bottled Beer', 'Bottled Wine', 'Non-Grat Svc Charges', 'No-Category'];
        let html = '';
        
        categories.forEach(cat => {
            const sales = data.category_sales?.[cat] || 0;
            const bartips = data.category_tips?.bartips?.[cat] || 0;
            const servertips = data.category_tips?.servertips?.[cat] || 0;
            const expotips = data.category_tips?.expotips?.[cat] || 0;
            const runnertips = data.category_tips?.runnertips?.[cat] || 0;
            
            html += `
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #eee;">${cat}</td>
                    <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">${sales.toFixed(2)}</td>
                    <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">${bartips.toFixed(2)}</td>
                    <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">${servertips.toFixed(2)}</td>
                    <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">${expotips.toFixed(2)}</td>
                    <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">${runnertips.toFixed(2)}</td>
                </tr>
            `;
        });
        
        const deferredAmount = data.deferred_amount || 0;
        html += `
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">Deferred amount</td>
                <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">${deferredAmount.toFixed(2)}</td>
                <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">0.00</td>
                <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">0.00</td>
                <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">0.00</td>
                <td style="padding: 8px; text-align: right; border-bottom: 1px solid #eee;">0.00</td>
            </tr>
        `;
        
        tbody.innerHTML = html;
        
        // Update totals
        document.getElementById('categoryTotalSales').textContent = data.total_sales?.toFixed(2) || '0.00';
        document.getElementById('categoryTotalBartips').textContent = data.total_bartips?.toFixed(2) || '0.00';
        document.getElementById('categoryTotalServertips').textContent = data.total_servertips?.toFixed(2) || '0.00';
        document.getElementById('categoryTotalExpotips').textContent = data.total_expotips?.toFixed(2) || '0.00';
        document.getElementById('categoryTotalRunnertips').textContent = data.total_runnertips?.toFixed(2) || '0.00';
        updateServerCategorySummaryExtras();
        
        // Auto-fill payout tips if empty
        const barTipsInput = document.getElementById('serverBarTips');
        if (barTipsInput && !options.preserveManualValues && (!barTipsInput.value || parseFloat(barTipsInput.value) === 0)) {
            barTipsInput.value = data.total_bartips?.toFixed(2) || '0.00';
        }
        const busserTipsInput = document.getElementById('serverBusserTips');
        if (busserTipsInput && !options.preserveManualValues && (!busserTipsInput.value || parseFloat(busserTipsInput.value) === 0)) {
            busserTipsInput.value = data.total_servertips?.toFixed(2) || '0.00';
        }
        const expoTipsInput = document.getElementById('serverExpoTips');
        if (expoTipsInput && !options.preserveManualValues && (!expoTipsInput.value || parseFloat(expoTipsInput.value) === 0)) {
            expoTipsInput.value = data.total_expotips?.toFixed(2) || '0.00';
        }
        const runnerTipsInput = document.getElementById('serverRunnerTips');
        if (runnerTipsInput && !options.preserveManualValues && (!runnerTipsInput.value || parseFloat(runnerTipsInput.value) === 0)) {
            runnerTipsInput.value = data.total_runnertips?.toFixed(2) || '0.00';
        }
        
        // Trigger recalculation
        updateServerTipsCalculations();
        
    } catch (e) {
        console.warn('Failed to load category breakdown:', e);
    }
}

// ========================
// BARTENDER TIPS FUNCTIONS
// ========================

function fetchBartenderTipsFromToast() {
    const bartenderSelect = document.getElementById('bartenderTipsWorker');
    const bartenderVal = bartenderSelect?.value;
    const bartenderOpt = bartenderSelect?.querySelector(`sl-option[value="${bartenderVal}"]`);
    const worker = bartenderOpt?.getAttribute('data-worker-name') || bartenderVal;
    const date = document.getElementById('bartenderTipsDate')?.value;
    
    if (!worker || !date) {
        showToast('Please select bartender and date', 'warning');
        return;
    }
    
    showLoading('Fetching data from Toast...');
    
    setTimeout(() => {
        document.getElementById('bartenderCashTips').value = (Math.random() * 80).toFixed(2);
        document.getElementById('bartenderCreditTips').value = (Math.random() * 300).toFixed(2);
        document.getElementById('bartenderNetSales').value = (Math.random() * 1500 + 800).toFixed(2);
        document.getElementById('bartenderHours').value = (Math.random() * 4 + 4).toFixed(2);
        
        document.getElementById('bartenderTipsForm').style.display = 'block';
        showToast('Data fetched successfully', 'success');
        hideLoading();
    }, 1000);
}

async function saveBartenderTips() {
    const date = document.getElementById('bartenderTipsDate')?.value;
    const bucket = document.getElementById('bartenderTipsBucket')?.value;

    if (!date || !bucket) {
        showToast('Please select date and bar location', 'warning');
        return;
    }

    showLoading('Saving bartender tips...');

    try {
        const response = await fetch(`${LOCAL_API}/bartender-defaults`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                date,
                bucket,
                cash_tips: parseFloat(document.getElementById('btCashTips')?.value || 0),
                credit_tips: parseFloat(document.getElementById('btCreditTips')?.value || 0),
                net_sales: parseFloat(document.getElementById('btNetSales')?.value || 0),
                busser_tips: parseFloat(document.getElementById('btBusserTips')?.value || 0),
                expo_tips: parseFloat(document.getElementById('btExpoTips')?.value || 0),
                runner_tips: parseFloat(document.getElementById('btRunnerTips')?.value || 0)
            })
        });

        if (!response.ok) {
            throw new Error('Failed to save bartender tips');
        }

        showToast('Bartender tips saved', 'success');
    } catch (error) {
        console.error('Error saving bartender tips:', error);
        showToast('Failed to save bartender tips', 'error');
    } finally {
        hideLoading();
    }
}

function pushBartenderTipsToPayouts() {
    if (!confirm('Push these tips to payouts?')) return;
    
    showLoading('Pushing to payouts...');
    
    setTimeout(() => {
        showToast('Tips pushed to payouts', 'success');
        hideLoading();
    }, 800);
}

// ==================
// NEW BARTENDER TIPS FUNCTIONS (Group Mode)
// ==================

let bartenderDefaultsData = null;
let selectedBartenders = new Set();

async function loadBartenderDefaults() {
    const date = document.getElementById('bartenderTipsDate')?.value;
    const bucket = document.getElementById('bartenderTipsBucket')?.value;
    
    if (!date || !bucket) {
        showToast('Please select date and bar location', 'warning');
        return;
    }
    
    showLoading('Fetching bartender data...');
    
    try {
        const response = await fetch(`${LOCAL_API}/bartender-defaults?date=${encodeURIComponent(date)}&bucket=${encodeURIComponent(bucket)}`);
        
        if (!response.ok) {
            throw new Error('Failed to fetch defaults');
        }
        
        const data = await response.json();
        bartenderDefaultsData = data;
        const hasOverride = !!data.existing_override?.is_override;
        
        // Populate Main Figures
        document.getElementById('btCashTips').value = data.cash_tips?.toFixed(2) || '0.00';
        document.getElementById('btCreditTips').value = data.credit_card_tips?.toFixed(2) || '0.00';
        document.getElementById('btNetSales').value = data.net_sales?.toFixed(2) || '0.00';
        
        // Populate Add Tips for Payout
        document.getElementById('btBusserTips').value = data.servertips?.toFixed(2) || '0.00';
        document.getElementById('btExpoTips').value = data.expotips?.toFixed(2) || '0.00';
        document.getElementById('btRunnerTips').value = data.runnertips?.toFixed(2) || '0.00';
        
        // Show the cards
        document.getElementById('bartenderMainFigures').style.display = 'block';
        document.getElementById('bartenderPayoutTips').style.display = 'block';
        
        // Update URL with current params for sharing
        updateUrlWithParams('bartender-tips', { bucket, business_date: date });
        
        // Load bartenders list
        await loadBartendersList(date, bucket, data.bartenders || []);
        
        // Render category table
        renderBartenderCategoryTable(data);
        
        showToast(hasOverride ? 'Saved bartender override loaded' : 'Data loaded successfully', 'success');
    } catch (error) {
        console.error('Error loading bartender defaults:', error);
        showToast('Failed to load bartender data', 'error');
    } finally {
        hideLoading();
    }
}

async function loadBartendersList(date, bucket, defaultBartenders) {
    const showAll = document.getElementById('showAllBartenders')?.checked || false;
    const container = document.getElementById('bartendersList');
    
    let bartenders = [];
    
    if (showAll) {
        // Load all bartenders with bar job
        try {
            const response = await fetch(`${LOCAL_API}/payouts/suggested-assignments?bucket=${encodeURIComponent(bucket)}&date=${encodeURIComponent(date)}&show_all=1`);
            const data = await response.json();
            bartenders = data.assignments?.Bartender || [];
        } catch (e) {
            console.error('Error loading all bartenders:', e);
        }
    } else {
        // Load bartenders who worked this bar on this date
        bartenders = defaultBartenders || [];
        
        // Also get pushed/committed bartenders
        try {
            const response = await fetch(`${LOCAL_API}/bartender/pushed-list?date=${encodeURIComponent(date)}&bucket=${encodeURIComponent(bucket)}&include_committed=1`);
            const data = await response.json();
            const pushed = data.workers || [];
            bartenders = [...new Set([...bartenders, ...pushed])];
        } catch (e) {
            console.error('Error loading pushed bartenders:', e);
        }
    }
    
    // Filter out placeholder names
    const barred = new Set(['am bar', 'sunset bar', 'low bar', 'low', 'ww bar', 'ew bar']);
    bartenders = bartenders.filter(n => !barred.has((n || '').toLowerCase()));
    
    // Render the list
    if (bartenders.length === 0) {
        container.innerHTML = '<p style="color: var(--sl-color-neutral-500); font-style: italic; margin: 0;">No bartenders found for this date/bar</p>';
        selectedBartenders.clear();
    } else {
        // Pre-select all by default
        selectedBartenders = new Set(bartenders);
        
        let html = '';
        bartenders.forEach(name => {
            const safeName = String(name).replace(/"/g, '&quot;');
            html += `
                <sl-checkbox data-worker="${safeName}" value="${escapeHtml(name)}" checked style="display: block; margin: 4px 0;">
                    ${escapeHtml(name)}
                </sl-checkbox>
            `;
        });
        container.innerHTML = html;
        // Attach explicit listeners so changes always trigger recalc.
        container.querySelectorAll('sl-checkbox').forEach(cb => {
            cb.addEventListener('sl-change', () => {
                syncSelectedBartendersFromUI();
                updateBartenderCount();
                updateBartenderPreview();
            });
        });
    }
    
    updateBartenderCount();
    updateBartenderPreview();
}

function toggleBartenderSelection(name, checked) {
    syncSelectedBartendersFromUI();
    updateBartenderCount();
    updateBartenderPreview();
}

function syncSelectedBartendersFromUI() {
    const checkboxes = document.querySelectorAll('#bartendersList sl-checkbox');
    if (!checkboxes || checkboxes.length === 0) return;
    const next = new Set();
    checkboxes.forEach(cb => {
        if (cb.checked) {
            const name = ((cb.getAttribute('data-worker') || cb.value || '').trim());
            if (name) next.add(name);
        }
    });
    selectedBartenders = next;
}

function unselectAllBartenders() {
    selectedBartenders.clear();
    document.querySelectorAll('#bartendersList sl-checkbox').forEach(cb => {
        cb.checked = false;
    });
    syncSelectedBartendersFromUI();
    updateBartenderCount();
    updateBartenderPreview();
}

async function toggleShowAllBartenders() {
    const date = document.getElementById('bartenderTipsDate')?.value;
    const bucket = document.getElementById('bartenderTipsBucket')?.value;
    
    if (date && bucket && bartenderDefaultsData) {
        await loadBartendersList(date, bucket, bartenderDefaultsData.bartenders || []);
    }
}

function updateBartenderCount() {
    syncSelectedBartendersFromUI();
    const count = selectedBartenders.size;
    document.getElementById('bartenderCount').textContent = `${count} selected`;
}

function onNetSalesChange() {
    // Auto-calculate payout tips based on net sales percentages
    const netSales = parseFloat(document.getElementById('btNetSales')?.value || 0);
    
    // Only auto-calculate if we have category data
    if (bartenderDefaultsData && bartenderDefaultsData.category_totals) {
        const totals = bartenderDefaultsData.category_totals;
        let foodSales = 0;
        let totalSales = 0;
        
        Object.entries(totals).forEach(([cat, amt]) => {
            totalSales += amt;
            if (cat === 'Food') {
                foodSales = amt;
            }
        });
        
        // Calculate: Busser 2% of total, Expo 1% of food, Runner 0.5% of food
        const busser = totalSales * 0.02;
        const expo = foodSales * 0.01;
        const runner = foodSales * 0.005;
        
        document.getElementById('btBusserTips').value = busser.toFixed(2);
        document.getElementById('btExpoTips').value = expo.toFixed(2);
        document.getElementById('btRunnerTips').value = runner.toFixed(2);
    }
    
    updateBartenderPreview();
}

function updateBartenderPreview() {
    syncSelectedBartendersFromUI();
    const names = Array.from(selectedBartenders);
    const n = names.length;
    
    const card = document.getElementById('bartenderPreviewCard');
    const tableBody = document.querySelector('#bartenderPreviewTable tbody');
    const note = document.getElementById('bartenderPreviewNote');
    
    if (n === 0) {
        card.style.display = 'none';
        return;
    }
    
    const cash = parseFloat(document.getElementById('btCashTips')?.value || 0);
    const credit = parseFloat(document.getElementById('btCreditTips')?.value || 0);
    const net = parseFloat(document.getElementById('btNetSales')?.value || 0);
    const busser = parseFloat(document.getElementById('btBusserTips')?.value || 0);
    const expo = parseFloat(document.getElementById('btExpoTips')?.value || 0);
    const runner = parseFloat(document.getElementById('btRunnerTips')?.value || 0);
    
    const per = {
        cash: cash / n,
        credit: credit / n,
        net: net / n,
        busser: busser / n,
        expo: expo / n,
        runner: runner / n
    };
    
    let html = '';
    names.forEach(name => {
        html += `
            <tr data-name="${escapeHtml(name)}">
                <td>${escapeHtml(name)}</td>
                <td>$${per.cash.toFixed(2)}</td>
                <td>$${per.credit.toFixed(2)}</td>
                <td>$${per.net.toFixed(2)}</td>
                <td>$${per.busser.toFixed(2)}</td>
                <td>$${per.expo.toFixed(2)}</td>
                <td>$${per.runner.toFixed(2)}</td>
                <td class="status-pushed" data-bartender="${escapeHtml(name)}">—</td>
                <td class="status-committed" data-bartender="${escapeHtml(name)}">—</td>
                <td>
                    <sl-button size="small" variant="success" onclick="pushSingleBartenderTips('${name.replace(/'/g, "\\'")}')">Push</sl-button>
                    <sl-button size="small" variant="danger" onclick="undoSingleBartenderTips('${name.replace(/'/g, "\\'")}')">Undo</sl-button>
                </td>
            </tr>
        `;
    });
    
    tableBody.innerHTML = html;
    card.style.display = 'block';
    
    note.textContent = `${n} bartender${n > 1 ? 's' : ''} selected; each shows 1/${n} of totals.`;
    
    // Refresh status for all rows
    refreshAllBartenderStatus();
}

function renderBartenderCategoryTable(data) {
    const card = document.getElementById('bartenderCategoryCard');
    const tableBody = document.querySelector('#bartenderCategoryTable tbody');
    
    if (!data.category_totals || Object.keys(data.category_totals).length === 0) {
        card.style.display = 'none';
        return;
    }
    
    const totals = data.category_totals || {};
    const breakdown = data.category_tip_breakdown || {};
    const svBreak = breakdown.servertips || {};
    const exBreak = breakdown.expotips || {};
    const rnBreak = breakdown.runnertips || {};
    
    const cats = ['Food', 'Wine', 'Draft Beer', 'Liquor', 'NA Beverage', 'Bottled Beer', 'Bottled Wine', 'Non-Grat Svc Charges'];
    let html = '';
    let sumSales = 0, sumSv = 0, sumEx = 0, sumRn = 0;
    
    cats.forEach(cat => {
        const s = Number(totals[cat] || 0);
        const sv = Number(svBreak[cat] || 0);
        const ex = Number(exBreak[cat] || 0);
        const rn = Number(rnBreak[cat] || 0);
        
        if (s > 0 || sv > 0 || ex > 0 || rn > 0) {
            sumSales += s;
            sumSv += sv;
            sumEx += ex;
            sumRn += rn;
            
            html += `
                <tr>
                    <td>${cat}</td>
                    <td>$${s.toFixed(2)}</td>
                    <td>$${sv.toFixed(2)}</td>
                    <td>$${ex.toFixed(2)}</td>
                    <td>$${rn.toFixed(2)}</td>
                </tr>
            `;
        }
    });
    
    // Total row
    html += `
        <tr style="font-weight: bold; background: var(--sl-color-neutral-100);">
            <td>Total</td>
            <td>$${sumSales.toFixed(2)}</td>
            <td>$${sumSv.toFixed(2)}</td>
            <td>$${sumEx.toFixed(2)}</td>
            <td>$${sumRn.toFixed(2)}</td>
        </tr>
    `;
    
    tableBody.innerHTML = html;
    card.style.display = 'block';
}

async function pushSingleBartenderTips(name) {
    syncSelectedBartendersFromUI();
    const date = document.getElementById('bartenderTipsDate')?.value;
    const bucket = document.getElementById('bartenderTipsBucket')?.value;
    
    if (!date || !bucket) {
        showToast('Date and bucket required', 'warning');
        return;
    }
    
    const n = selectedBartenders.size || 1;
    const cash = parseFloat(document.getElementById('btCashTips')?.value || 0) / n;
    const credit = parseFloat(document.getElementById('btCreditTips')?.value || 0) / n;
    const net = parseFloat(document.getElementById('btNetSales')?.value || 0) / n;
    const busser = parseFloat(document.getElementById('btBusserTips')?.value || 0) / n;
    const expo = parseFloat(document.getElementById('btExpoTips')?.value || 0) / n;
    const runner = parseFloat(document.getElementById('btRunnerTips')?.value || 0) / n;
    const totalCash = parseFloat(document.getElementById('btCashTips')?.value || 0);
    const totalCredit = parseFloat(document.getElementById('btCreditTips')?.value || 0);
    const totalNet = parseFloat(document.getElementById('btNetSales')?.value || 0);
    const totalBusser = parseFloat(document.getElementById('btBusserTips')?.value || 0);
    const totalExpo = parseFloat(document.getElementById('btExpoTips')?.value || 0);
    const totalRunner = parseFloat(document.getElementById('btRunnerTips')?.value || 0);
    
    // Check if all zero
    if (busser === 0 && expo === 0 && runner === 0) {
        if (!confirm('All Busser/Expo/Runner amounts are 0. Push anyway?')) {
            return;
        }
    }
    
    showLoading(`Pushing tips for ${name}...`);
    
    try {
        const response = await fetch(`${LOCAL_API}/bartender/push`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                bartender: name,
                date: date,
                bucket: bucket,
                bussertips: busser,
                expotips: expo,
                runnertips: runner,
                per_cash: cash,
                per_credit: credit,
                per_net: net,
                total_cash: totalCash,
                total_credit: totalCredit,
                total_net: totalNet,
                total_busser: totalBusser,
                total_expo: totalExpo,
                total_runner: totalRunner
            })
        });
        
        if (!response.ok) {
            throw new Error('Push failed');
        }
        
        showToast(`Tips pushed for ${name}`, 'success');
        await refreshBartenderStatus(name);
    } catch (error) {
        console.error('Error pushing tips:', error);
        showToast(`Failed to push tips for ${name}`, 'error');
    } finally {
        hideLoading();
    }
}

async function undoSingleBartenderTips(name) {
    const date = document.getElementById('bartenderTipsDate')?.value;
    const bucket = document.getElementById('bartenderTipsBucket')?.value;
    
    if (!date || !bucket) {
        showToast('Date and bucket required', 'warning');
        return;
    }
    
    showLoading(`Undoing tips for ${name}...`);
    
    try {
        const response = await fetch(`${LOCAL_API}/bartender/undo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                bartender: name,
                date: date,
                bucket: bucket
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`Tips undone for ${name}`, 'success');
        } else {
            showToast(data.message || 'No tips to undo', 'warning');
        }
        
        bartenderDefaultsData = null;
        await loadBartenderDefaults();
        await refreshBartenderStatus(name);
    } catch (error) {
        console.error('Error undoing tips:', error);
        showToast(`Failed to undo tips for ${name}`, 'error');
    } finally {
        hideLoading();
    }
}

async function refreshBartenderStatus(name) {
    const date = document.getElementById('bartenderTipsDate')?.value;
    const bucket = document.getElementById('bartenderTipsBucket')?.value;
    
    if (!date || !bucket) return;
    
    try {
        const response = await fetch(`${LOCAL_API}/bartender/status?bartender=${encodeURIComponent(name)}&bucket=${encodeURIComponent(bucket)}&date=${encodeURIComponent(date)}`);
        
        if (!response.ok) return;
        
        const data = await response.json();
        
        const pushedEl = document.querySelector(`.status-pushed[data-bartender="${CSS.escape(name)}"]`);
        const committedEl = document.querySelector(`.status-committed[data-bartender="${CSS.escape(name)}"]`);
        
        if (pushedEl) {
            const p = data.pushed || {};
            const total = (p.Busser || 0) + (p.Expo || 0) + (p.Runner || 0);
            const hasPushedRecord = (data.pushed_count || 0) > 0;
            pushedEl.innerHTML = `
                <div>Busser: $${(p.Busser || 0).toFixed(2)}</div>
                <div>Expo: $${(p.Expo || 0).toFixed(2)}</div>
                <div>Runner: $${(p.Runner || 0).toFixed(2)}</div>
            `;
            // Color as pushed whenever a push record exists, even if all values are 0.
            pushedEl.classList.toggle('has-unpaid', hasPushedRecord);
        }
        
        if (committedEl) {
            const c = data.committed || {};
            const total = (c.Busser || 0) + (c.Expo || 0) + (c.Runner || 0);
            committedEl.innerHTML = `
                <div>Busser: $${(c.Busser || 0).toFixed(2)}</div>
                <div>Expo: $${(c.Expo || 0).toFixed(2)}</div>
                <div>Runner: $${(c.Runner || 0).toFixed(2)}</div>
            `;
            committedEl.classList.toggle('has-committed', total > 0);
        }
    } catch (e) {
        console.error('Error refreshing status:', e);
    }
}

async function refreshAllBartenderStatus() {
    const names = Array.from(selectedBartenders);
    for (const name of names) {
        await refreshBartenderStatus(name);
    }
}

// ==================
// PAYOUTS FUNCTIONS
// ==================

async function loadPayoutsData() {
    const bucket = document.getElementById('payoutBucket')?.value;
    const date = document.getElementById('payoutDate')?.value;
    const showAll = document.getElementById('payoutShowAll')?.checked || false;
    
    if (!bucket || !date) {
        showToast('Please select bucket and date', 'warning');
        return;
    }
    
    showLoading('Loading payouts data...');
    
    try {
        // Fetch unpaid amounts
        const params = new URLSearchParams({ bucket, date });
        const unpaidResp = await fetch(`${LOCAL_API}/payouts/unpaid?${params}`);
        const unpaidData = await unpaidResp.json();
        
        // Set unpaid amounts
        document.getElementById('payoutBartenderAmount').value = (unpaidData.unpaid?.Bartender || 0).toFixed(2);
        document.getElementById('payoutBusserAmount').value = (unpaidData.unpaid?.Busser || 0).toFixed(2);
        document.getElementById('payoutExpoAmount').value = (unpaidData.unpaid?.Expo || 0).toFixed(2);
        document.getElementById('payoutRunnerAmount').value = (unpaidData.unpaid?.Runner || 0).toFixed(2);
        
        // Fetch suggested assignments based on job titles and date
        const showAll = document.getElementById('payoutShowAll')?.checked || false;
        const suggestedParams = new URLSearchParams({ bucket, date, show_all: showAll ? '1' : '0' });
        const suggestedResp = await fetch(`${LOCAL_API}/payouts/suggested-assignments?${suggestedParams}`);
        const suggestedData = await suggestedResp.json();
        
        // Update assignment boxes with suggested workers for each category
        updatePayoutAssignmentBoxesFromSuggestions(suggestedData.assignments || {});
        
        // Also fetch saved assignments to pre-select checkboxes
        const assignResp = await fetch(`${LOCAL_API}/payouts/assignments?bucket=${bucket}`);
        const savedAssignments = await assignResp.json();
        
        // Set checkboxes from saved assignments
        Object.entries(savedAssignments).forEach(([dest, workers]) => {
            workers.forEach(worker => {
                const list = document.getElementById(`assign-${dest}`);
                if (list) {
                    const cb = list.querySelector(`sl-checkbox[value="${worker}"]`);
                    if (cb) cb.checked = true;
                }
            });
            updateAssignmentCount(dest);
        });

        refreshPayoutRoleCorrectionWorkerOptions();
        await loadPayoutRoleCorrections();
        
        // Fetch and display unpaid breakdown
        const breakdownResp = await fetch(`${LOCAL_API}/payouts/unpaid-breakdown?${params}`);
        const breakdown = await breakdownResp.json();
        renderUnpaidBreakdown(breakdown, bucket, date);
        
        // Fetch and display committed payouts
        const committedResp = await fetch(`${LOCAL_API}/payouts/committed?${params}`);
        const committed = await committedResp.json();
        renderCommittedPayouts(committed, bucket, date);
        
        // Update URL with current params for sharing
        updateUrlWithParams('payouts', { bucket, business_date: date });
        
        document.getElementById('payoutsContent').style.display = 'block';
        showToast('Payouts data loaded', 'success');
    } catch (error) {
        showToast('Failed to load payouts data', 'error');
        console.error(error);
    } finally {
        hideLoading();
    }
}

// Update payout assignment boxes with workers who worked
function updatePayoutAssignmentBoxes(workersForDate, showAll) {
    const destinations = ['Bartender', 'Busser', 'Expo', 'Runner'];
    const workersToShow = showAll ? WORKERS : (workersForDate.length > 0 ? workersForDate : WORKERS);
    
    destinations.forEach(dest => {
        const list = document.getElementById(`assign-${dest}`);
        if (list) {
            list.innerHTML = workersToShow.map(w => `
                <label class="assignment-item">
                    <sl-checkbox name="assign_${dest}" value="${w}"></sl-checkbox>
                    <span>${w}</span>
                </label>
            `).join('');
        }
        updateAssignmentCount(dest);
    });
    
    // Re-add change listeners
    destinations.forEach(dest => {
        const list = document.getElementById(`assign-${dest}`);
        if (list) {
            list.addEventListener('sl-change', () => updateAssignmentCount(dest));
        }
    });
}

// Update payout assignment boxes based on suggested assignments from API
function updatePayoutAssignmentBoxesFromSuggestions(assignments) {
    const destinations = ['Bartender', 'Busser', 'Expo', 'Runner'];
    
    destinations.forEach(dest => {
        const list = document.getElementById(`assign-${dest}`);
        const workers = assignments[dest] || [];
        
        if (list) {
            if (workers.length > 0) {
                list.innerHTML = workers.map(w => `
                    <label class="assignment-item">
                        <sl-checkbox name="assign_${dest}" value="${w}"></sl-checkbox>
                        <span>${w}</span>
                    </label>
                `).join('');
            } else {
                list.innerHTML = '<p style="color: #999; font-style: italic; padding: 8px;">0 assigned</p>';
            }
        }
        updateAssignmentCount(dest);
    });
    
    // Re-add change listeners
    destinations.forEach(dest => {
        const list = document.getElementById(`assign-${dest}`);
        if (list) {
            list.addEventListener('sl-change', () => updateAssignmentCount(dest));
        }
    });
}

// Render unpaid breakdown table
function renderUnpaidBreakdown(breakdown, bucket, date) {
    const container = document.getElementById('unpaidBreakdownTable');
    if (!container) return;
    
    if (breakdown.length === 0) {
        container.innerHTML = '<p style="color: #666; font-style: italic;">No unpaid pushed tips for this date and bucket.</p>';
        return;
    }
    
    let html = `
        <p style="margin-bottom: 12px; color: #666; font-size: 14px;">
            Unpaid Pushed Breakdown (${date}, ${bucket})
        </p>
        <table class="data-table" style="width: 100%; border-collapse: collapse; font-size: 14px;">
            <thead>
                <tr style="background: #f5f5f5;">
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">Server</th>
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">Destination</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Amount</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    let total = 0;
    breakdown.forEach(row => {
        total += row.amount;
        html += `
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">${row.server}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">${row.destination}</td>
                <td style="padding: 10px; text-align: right; border-bottom: 1px solid #eee;">$${row.amount.toFixed(2)}</td>
            </tr>
        `;
    });
    
    html += `
            </tbody>
            <tfoot>
                <tr style="background: #f9f9f9; font-weight: bold;">
                    <td style="padding: 10px; border-top: 2px solid #ddd;">Total</td>
                    <td style="padding: 10px; border-top: 2px solid #ddd;"></td>
                    <td style="padding: 10px; text-align: right; border-top: 2px solid #ddd;">$${total.toFixed(2)}</td>
                </tr>
            </tfoot>
        </table>
    `;
    
    container.innerHTML = html;
}

// Render committed payouts table
function renderCommittedPayouts(committed, bucket, date) {
    const container = document.getElementById('committedPayoutsTable');
    if (!container) return;
    
    if (committed.length === 0) {
        container.innerHTML = '<p style="color: #666; font-style: italic;">No committed payouts for this date and bucket.</p>';
        return;
    }
    
    let html = `
        <p style="margin-bottom: 12px; color: #666; font-size: 14px;">
            Committed Payouts (${date}, ${bucket})
        </p>
        <table class="data-table" style="width: 100%; border-collapse: collapse; font-size: 14px;">
            <thead>
                <tr style="background: #f5f5f5;">
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">Worker</th>
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">Destination</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Amount</th>
                    <th style="padding: 10px; text-align: center; border-bottom: 2px solid #ddd;">Session</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    let total = 0;
    committed.forEach(row => {
        total += row.amount;
        const sessionShort = row.session_id ? row.session_id.split('_').pop() : '-';
        html += `
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">${row.worker_name}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">${row.destination}</td>
                <td style="padding: 10px; text-align: right; border-bottom: 1px solid #eee;">$${row.amount.toFixed(2)}</td>
                <td style="padding: 10px; text-align: center; border-bottom: 1px solid #eee;"><code>${sessionShort}</code></td>
            </tr>
        `;
    });
    
    html += `
            </tbody>
            <tfoot>
                <tr style="background: #f9f9f9; font-weight: bold;">
                    <td style="padding: 10px; border-top: 2px solid #ddd;">Total</td>
                    <td style="padding: 10px; border-top: 2px solid #ddd;"></td>
                    <td style="padding: 10px; text-align: right; border-top: 2px solid #ddd;">$${total.toFixed(2)}</td>
                    <td style="padding: 10px; border-top: 2px solid #ddd;"></td>
                </tr>
            </tfoot>
        </table>
    `;
    
    container.innerHTML = html;
}

async function savePayoutAssignments() {
    showLoading('Saving assignments...');
    
    const bucket = document.getElementById('payoutBucket')?.value;
    const assignments = {};
    
    ['Bartender', 'Busser', 'Expo', 'Runner'].forEach(dest => {
        const list = document.getElementById(`assign-${dest}`);
        if (list) {
            const checked = Array.from(list.querySelectorAll('sl-checkbox[checked]')).map(cb => cb.value);
            assignments[dest] = checked;
        }
    });
    
    try {
        const response = await fetch(`${LOCAL_API}/payouts/assignments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bucket, assignments })
        });
        
        if (response.ok) {
            showToast('Assignments saved', 'success');
        } else {
            throw new Error('Failed to save');
        }
    } catch (error) {
        showToast('Failed to save assignments', 'error');
    } finally {
        hideLoading();
    }
}

async function previewPayoutDistribution() {
    showLoading('Calculating distribution...');

    try {
        const calc = await buildPayoutDistributions();
        setTimeout(() => {
            renderPayoutPreview(calc.distributions, calc.grandTotal);
            showToast('Distribution preview ready', 'success');
            hideLoading();
        }, 300);
    } catch (error) {
        console.error(error);
        showToast('Failed to calculate distribution', 'error');
        hideLoading();
    }
}

function renderPayoutPreview(distributions, grandTotal) {
    const section = document.getElementById('payoutPreviewSection');
    const meta = document.getElementById('payoutPreviewMeta');
    const table = document.getElementById('payoutPreviewTable');

    if (!section || !meta || !table) return;

    section.style.display = 'block';

    const bucket = document.getElementById('payoutBucket')?.value || '';
    const date = document.getElementById('payoutDate')?.value || '';

    meta.innerHTML = `
        <span class="pill">Bucket: ${bucket}</span>
        <span class="pill">Date: ${date}</span>
        <span class="kpi">Total: $${grandTotal.toFixed(2)}</span>
    `;

    let html = '<table class="data-table"><thead><tr><th>Worker</th><th>Destination</th><th>Split</th><th>Hours</th><th class="num-right">Amount</th></tr></thead><tbody>';

    distributions.forEach(d => {
        const modeLabel = d.split_mode === 'hourly' ? 'Hourly' : 'Even';
        const hoursText = (d.split_mode === 'hourly') ? Number(d.hours || 0).toFixed(2) : '—';
        html += `<tr><td>${d.worker}</td><td>${d.destination}</td><td>${modeLabel}</td><td>${hoursText}</td><td class="num-right">$${Number(d.amount).toFixed(2)}</td></tr>`;
    });

    html += `<tr style="font-weight: bold;"><td colspan="4">Total</td><td class="num-right">$${grandTotal.toFixed(2)}</td></tr>`;
    html += '</tbody></table>';

    table.innerHTML = html;
}

async function commitPayouts() {
    if (!confirm('Commit payouts to database? This will create payout records.')) return;

    showLoading('Committing payouts...');

    try {
        const calc = await buildPayoutDistributions();
        const selectedCount = ['Bartender', 'Busser', 'Expo', 'Runner']
            .reduce((sum, dest) => sum + ((calc.assignments?.[dest] || []).length), 0);

        if (selectedCount === 0 || !calc.distributions || calc.distributions.length === 0) {
            showToast('Select at least one worker in Worker Assignments before committing', 'warning');
            return;
        }

        const response = await fetch(`${LOCAL_API}/payouts/commit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bucket: calc.bucket, date: calc.date, distributions: calc.distributions })
        });

        if (response.ok) {
            showToast('Payouts committed successfully', 'success');
            await loadPayoutsData();
        } else {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.error || 'Failed to commit');
        }
    } catch (error) {
        showToast(error.message || 'Failed to commit payouts', 'error');
        console.error(error);
    } finally {
        hideLoading();
    }
}

async function rollbackCommittedPayouts() {
    const bucket = document.getElementById('payoutBucket')?.value;
    const date = document.getElementById('payoutDate')?.value;
    
    if (!bucket || !date) {
        showToast('Please select bucket and date', 'warning');
        return;
    }
    
    if (!confirm('Rollback the latest committed payout session? This will restore tips to the unpaid pool.')) {
        return;
    }
    
    showLoading('Rolling back committed payouts...');
    
    try {
        const response = await fetch(`${LOCAL_API}/payouts/rollback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bucket, date })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showToast(`Rolled back ${result.payouts_deleted} payouts`, 'success');
            // Run the same full refresh path as the "Load Data" button.
            await loadPayoutsData();
        } else {
            throw new Error(result.error || 'Failed to rollback');
        }
    } catch (error) {
        showToast('Failed to rollback: ' + error.message, 'error');
        console.error(error);
    } finally {
        hideLoading();
    }
}

// =====================
// REPORT FUNCTIONS
// =====================

async function loadDashboardMetrics() {
    showLoading('Loading dashboard metrics...');
    
    try {
        // Use most recent available orders file
        const ordersResponse = await executeDSLQuery({
            "from": { "source_file": "orders_full_20260204.json", "alias": "o" },
            "select": [{"expr": "o.guid", "alias": "guid"}]
        });
        
        const empResponse = await executeDSLQuery({
            "from": { "source_file": "labor_v1_employees.json", "alias": "e" },
            "select": [{"expr": "e.guid", "alias": "guid"}]
        });
        
        const timeResponse = await executeDSLQuery({
            "from": { "source_file": "labor_v1_timeEntries_20260130.json", "alias": "t" },
            "select": [{"expr": "t.guid", "alias": "guid"}]
        });
        
        const ordersEl = document.getElementById('metric-orders');
        const empEl = document.getElementById('metric-employees');
        const timeEl = document.getElementById('metric-sales');
        
        if (ordersEl) ordersEl.textContent = (ordersResponse.total_count || 0).toLocaleString();
        if (empEl) empEl.textContent = (empResponse.total_count || 0).toLocaleString();
        if (timeEl) timeEl.textContent = (timeResponse.total_count || 0).toLocaleString();
        
        await loadCharts();
        
    } catch (error) {
        console.error('Failed to load dashboard:', error);
        showToast('Failed to load dashboard metrics', 'error');
    } finally {
        hideLoading();
    }
}

async function loadCharts() {
    try {
        const response = await executeDSLQuery({
            "from": { "source_file": "orders_full_20260204.json", "alias": "o" },
            "select": [
                {"expr": "o.approvalStatus", "alias": "Status"},
                {"expr": "COUNT(*)", "alias": "Count"}
            ],
            "group_by": [{"field": "o.approvalStatus"}]
        });
        
        const data = convertResponseToObjects(response);
        
        const ctx = document.getElementById('hourlyChart');
        if (ctx && data.length > 0) {
            // Set explicit dimensions to prevent canvas overflow
            ctx.width = ctx.parentElement.clientWidth;
            ctx.height = 250;
            
            if (charts.status) {
                charts.status.destroy();
                charts.status = null;
            }
            
            charts.status = new Chart(ctx.getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: data.map(d => d.Status || 'Unknown'),
                    datasets: [{
                        data: data.map(d => d.Count || 0),
                        backgroundColor: ['#667eea', '#764ba2', '#f093fb', '#f5576c']
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { 
                        legend: { 
                            position: 'right',
                            labels: {
                                boxWidth: 12,
                                font: { size: 12 }
                            }
                        } 
                    },
                    layout: {
                        padding: 10
                    }
                }
            });
        }
    } catch (error) {
        console.error('Failed to load charts:', error);
    }
}

async function executeDSLQuery(query) {
    const response = await fetch(`${JAQ_SERVER}/query/dsl`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: JSON.stringify(query) })
    });
    
    if (!response.ok) {
        throw new Error(`Query failed: ${await response.text()}`);
    }
    
    return await response.json();
}

function convertResponseToObjects(response) {
    if (!response.success || !response.rows) return [];
    return response.rows.map(row => {
        const obj = {};
        response.columns.forEach((col, i) => obj[col] = row[i]);
        return obj;
    });
}

async function runReport(reportKey) {
    const report = REPORT_QUERIES[reportKey];
    if (!report) {
        showToast(`Unknown report: ${reportKey}`, 'error');
        return;
    }
    
    currentReport = { key: reportKey, ...report };
    showLoading(`Running ${report.name}...`);
    
    try {
        const response = await executeDSLQuery(report.query);
        currentResults = convertResponseToObjects(response);
        
        document.getElementById('reportTitle').textContent = report.name;
        document.getElementById('reportDescription').textContent = report.description;
        renderTable('reportResultsTable', currentResults);
        
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('report-results-page').classList.add('active');
        
        showToast(`Loaded ${currentResults.length} rows`, 'success');
    } catch (error) {
        showToast(`Failed to run report: ${error.message}`, 'error');
    } finally {
        hideLoading();
    }
}

function renderTable(containerId, data) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    if (data.length === 0) {
        container.innerHTML = `<div class="empty-state"><sl-icon name="inbox"></sl-icon><h3>No Data</h3></div>`;
        return;
    }
    
    const columns = Object.keys(data[0]);
    let html = '<table class="data-table"><thead><tr>';
    columns.forEach(col => {
        html += `<th>${col.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</th>`;
    });
    html += '</tr></thead><tbody>';
    
    data.forEach(row => {
        html += '<tr>';
        columns.forEach(col => {
            let val = row[col];
            if (val === null || val === undefined) val = '<span class="null-value">-</span>';
            else if (typeof val === 'number') val = val.toLocaleString();
            html += `<td>${val}</td>`;
        });
        html += '</tr>';
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

// Query Builder
function loadExampleQuery() {
    const textarea = document.getElementById('dslQueryText');
    if (textarea) {
        textarea.value = JSON.stringify({
            "from": { "source_file": "orders_full_20260130.json", "alias": "o" },
            "select": [
                {"expr": "o.guid", "alias": "Order_GUID"},
                {"expr": "o.displayNumber", "alias": "Order_Number"},
                {"expr": "o.openedDate", "alias": "Opened_Date"},
                {"expr": "o.totalAmount", "alias": "Total"}
            ],
            "order_by": [{"field": "o.openedDate", "direction": "DESC"}],
            "limit": 50
        }, null, 2);
        showToast('Example query loaded - Jan 30, 2026 data', 'success');
    }
}

// Fill in quick date selection for query
function fillQuickDate() {
    const select = document.getElementById('quickDateSelect');
    const date = select?.value;
    if (!date) return;
    
    // Convert date to filename format
    const dateStr = date.replace(/-/g, '');
    const filename = `orders_full_${dateStr}.json`;
    
    const textarea = document.getElementById('dslQueryText');
    if (textarea) {
        textarea.value = JSON.stringify({
            "from": { "source_file": filename, "alias": "o" },
            "select": [
                {"expr": "o.guid", "alias": "Order_GUID"},
                {"expr": "o.displayNumber", "alias": "Order_Number"},
                {"expr": "o.openedDate", "alias": "Opened_Date"},
                {"expr": "o.totalAmount", "alias": "Total"},
                {"expr": "o.orderType", "alias": "Type"}
            ],
            "order_by": [{"field": "o.openedDate", "direction": "DESC"}],
            "limit": 100
        }, null, 2);
        showToast(`Query for ${date} loaded`, 'success');
    }
    
    // Also set the date inputs
    document.getElementById('queryStartDate').value = date;
    document.getElementById('queryEndDate').value = date;
}

async function executeCustomQuery() {
    const queryText = document.getElementById('dslQueryText')?.value.trim();
    if (!queryText) {
        showToast('Please enter a query', 'warning');
        return;
    }
    
    let query;
    try {
        query = JSON.parse(queryText);
    } catch (error) {
        showToast(`Invalid JSON: ${error.message}`, 'error');
        return;
    }
    
    showLoading('Executing query...');
    
    try {
        const response = await executeDSLQuery(query);
        currentResults = convertResponseToObjects(response);
        
        document.getElementById('queryResults').style.display = 'block';
        document.getElementById('resultCount').textContent = `${currentResults.length} rows`;
        renderTable('queryResultsTable', currentResults);
        
        showToast(`Query returned ${currentResults.length} rows`, 'success');
    } catch (error) {
        showToast(`Query failed: ${error.message}`, 'error');
    } finally {
        hideLoading();
    }
}

// Export functions
async function exportCurrentReport() {
    if (!currentReport || currentResults.length === 0) {
        showToast('No data to export', 'warning');
        return;
    }
    await exportToCSV(currentResults, currentReport.name.replace(/\s+/g, '_').toLowerCase());
}

async function exportQueryResults() {
    if (currentResults.length === 0) {
        showToast('No data to export', 'warning');
        return;
    }
    await exportToCSV(currentResults, 'query_results');
}

async function exportToCSV(data, filename) {
    if (data.length === 0) return;
    
    const columns = Object.keys(data[0]);
    let csv = columns.join(',') + '\n';
    
    data.forEach(row => {
        const values = columns.map(col => {
            const val = row[col];
            if (val === null || val === undefined) return '';
            const str = String(val);
            if (str.includes(',') || str.includes('"') || str.includes('\n')) {
                return `"${str.replace(/"/g, '""')}"`;
            }
            return str;
        });
        csv += values.join(',') + '\n';
    });
    
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filename}_${new Date().toISOString().split('T')[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    showToast('Export downloaded', 'success');
}

async function refreshData() {
    showToast('Refreshing...', 'primary');
    await checkConnection();
    const activePage = document.querySelector('.page.active');
    if (activePage?.id === 'dashboard-page') {
        await loadDashboardMetrics();
    }
}


// =====================
// WORKER REPORT FUNCTIONS
// =====================

let workerReportData = [];

async function loadWorkerReport() {
    const startDate = document.getElementById('workerReportStartDate')?.value;
    const endDate = document.getElementById('workerReportEndDate')?.value;
    
    if (!startDate || !endDate) {
        showToast('Please select start and end dates', 'warning');
        return;
    }
    
    showLoading('Loading worker report...');
    
    try {
        const params = new URLSearchParams({
            start_date: startDate,
            end_date: endDate
        });
        
        const response = await fetch(`${LOCAL_API}/report?${params}`);
        
        if (!response.ok) {
            throw new Error('Failed to load report');
        }
        
        workerReportData = await response.json();
        
        renderWorkerReport(workerReportData);
        
        document.getElementById('workerReportContainer').style.display = 'block';
        document.getElementById('workerReportRowCount').textContent = `${workerReportData.length} rows`;
        
        showToast(`Loaded ${workerReportData.length} rows`, 'success');
    } catch (error) {
        console.error('Error loading worker report:', error);
        showToast('Failed to load worker report', 'error');
    } finally {
        hideLoading();
    }
}

function renderWorkerReport(data) {
    const container = document.getElementById('workerReportTable');
    
    if (data.length === 0) {
        container.innerHTML = '<p style="color: #666; padding: 20px;">No data found for the selected date range.</p>';
        return;
    }
    
    let html = `
        <table class="data-table" style="width: 100%; font-size: 13px;">
            <thead>
                <tr style="background: #f8f9fa;">
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">Date</th>
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">Worker</th>
                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #ddd;">Job Title</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Cash Tips</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Non-Cash Tips</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Gratuity</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Tips Paid Out</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Net Sales</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Tips Received</th>
                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #ddd;">Tip %</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    data.forEach(row => {
        html += `
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px;">${row.date}</td>
                <td style="padding: 8px; font-weight: 500;">${escapeHtml(row.worker)}</td>
                <td style="padding: 8px;">${escapeHtml(row.job_title)}</td>
                <td style="padding: 8px; text-align: right;">$${row.cash_tips.toFixed(2)}</td>
                <td style="padding: 8px; text-align: right;">$${row.credit_tips.toFixed(2)}</td>
                <td style="padding: 8px; text-align: right;">$${row.gratuity.toFixed(2)}</td>
                <td style="padding: 8px; text-align: right; color: #d32f2f;">$${row.tips_paid_out.toFixed(2)}</td>
                <td style="padding: 8px; text-align: right;">$${row.net_sales.toFixed(2)}</td>
                <td style="padding: 8px; text-align: right; color: #2e7d32;">$${row.tips_received.toFixed(2)}</td>
                <td style="padding: 8px; text-align: right;">${row.tip_pct.toFixed(2)}%</td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
}

async function exportWorkerReport() {
    if (workerReportData.length === 0) {
        showToast('No data to export', 'warning');
        return;
    }
    
    // Transform data for CSV export with friendly column names
    const exportData = workerReportData.map(row => ({
        Date: row.date,
        Worker: row.worker,
        'Job Title': row.job_title,
        'Cash Tips': row.cash_tips.toFixed(2),
        'Non-Cash Tips': row.credit_tips.toFixed(2),
        Gratuity: row.gratuity.toFixed(2),
        'Tips Paid Out': row.tips_paid_out.toFixed(2),
        'Net Sales': row.net_sales.toFixed(2),
        'Tips Received': row.tips_received.toFixed(2),
        'Tip % of Sales': row.tip_pct.toFixed(2) + '%'
    }));
    
    await exportToCSV(exportData, 'worker_report');
}

// Initialize worker report default dates
function initWorkerReportDates() {
    const today = new Date().toISOString().split('T')[0];
    const startDate = document.getElementById('workerReportStartDate');
    const endDate = document.getElementById('workerReportEndDate');
    
    if (startDate) startDate.value = today;
    if (endDate) endDate.value = today;
}

// Call on page load
document.addEventListener('DOMContentLoaded', () => {
    initWorkerReportDates();
});


// =====================
// SUGGEST FUNCTIONS
// =====================

// Initialize suggest page default date
function initSuggestDate() {
    const today = new Date().toISOString().split('T')[0];
    const dateInput = document.getElementById('suggestDate');
    
    // Check for URL parameter
    const urlParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
    const urlDate = urlParams.get('business_date');
    
    if (dateInput) {
        dateInput.value = urlDate || today;
    }
    
    // If we're on the suggest page and have a date (from URL or default), load suggestions
    if (window.location.hash.includes('suggest') && dateInput?.value) {
        // Delay slightly to let the page fully load
        setTimeout(() => loadSuggestions(), 100);
    }
}

// Call on page load
document.addEventListener('DOMContentLoaded', () => {
    initSuggestDate();
    initFetchPage();
});

async function loadSuggestions() {
    const dateInput = document.getElementById('suggestDate');
    
    // Get date from input first (user's selection takes priority)
    let date = dateInput?.value;
    
    // If no date in input, check URL parameter (for initial page load)
    if (!date) {
        const urlParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
        const urlDate = urlParams.get('business_date');
        if (urlDate && dateInput) {
            dateInput.value = urlDate;
            date = urlDate;
        }
    }
    
    if (!date) {
        showToast('Please select a date', 'warning');
        return;
    }
    
    // Update URL with date parameter
    updateUrlWithParams('suggest', { business_date: date });
    
    showLoading('Finding workers...');
    
    try {
        const params = new URLSearchParams({ date });
        const response = await fetch(`${LOCAL_API}/suggest?${params}`);
        
        if (!response.ok) {
            throw new Error('Failed to load suggestions');
        }
        
        const data = await response.json();
        
        renderSuggestions(data);
        
        document.getElementById('suggestContainer').style.display = 'block';
        
        if (data.count === 0) {
            showToast('All workers have pushed/committed their tips!', 'success');
        } else {
            showToast(`Found ${data.count} workers who need to push/commit tips`, 'primary');
        }
    } catch (error) {
        console.error('Error loading suggestions:', error);
        showToast('Failed to load suggestions', 'error');
    } finally {
        hideLoading();
    }
}

function renderSuggestions(data) {
    const container = document.getElementById('suggestTable');
    const title = document.getElementById('suggestTitle');
    const countBadge = document.getElementById('suggestCount');
    
    title.textContent = `Suggestions for ${data.date}`;
    countBadge.textContent = `${data.count} found`;
    
    if (data.suggestions.length === 0) {
        container.innerHTML = `
            <div style="padding: 40px; text-align: center; color: #2e7d32;">
                <sl-icon name="check-circle" style="font-size: 48px; color: #2e7d32;"></sl-icon>
                <h3 style="margin-top: 16px; color: #2e7d32;">All caught up!</h3>
                <p>All workers have pushed or committed their tips for this date.</p>
            </div>
        `;
        return;
    }
    
    let html = `
        <table class="data-table" style="width: 100%; font-size: 13px;">
            <thead>
                <tr style="background: #f8f9fa;">
                    <th style="padding: 12px; text-align: left; border-bottom: 2px solid #ddd;">Worker</th>
                    <th style="padding: 12px; text-align: left; border-bottom: 2px solid #ddd;">Location</th>
                    <th style="padding: 12px; text-align: left; border-bottom: 2px solid #ddd;">Reason</th>
                    <th style="padding: 12px; text-align: right; border-bottom: 2px solid #ddd;">Cash Tips</th>
                    <th style="padding: 12px; text-align: right; border-bottom: 2px solid #ddd;">Credit Card Tips</th>
                    <th style="padding: 12px; text-align: right; border-bottom: 2px solid #ddd;">Total Tips</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    data.suggestions.forEach(row => {
        const total = row.cash_tips + row.credit_tips;
        const bucket = row.bucket || '';
        const workerUrl = `#server-tips?business_date=${encodeURIComponent(data.date)}&worker=${encodeURIComponent(row.worker)}&bucket=${encodeURIComponent(bucket)}`;
        html += `
            <tr style="border-bottom: 1px solid #eee; cursor: pointer; transition: background-color 0.2s;" 
                onclick="window.location.href='${workerUrl}'"
                onmouseover="this.style.backgroundColor='#f5f5f5'"
                onmouseout="this.style.backgroundColor=''"
                title="Click to open Server Tips for ${escapeHtml(row.worker)} - ${escapeHtml(bucket)}">
                <td style="padding: 10px; font-weight: 500;">
                    <a href="${workerUrl}" style="color: #1976d2; text-decoration: none;" onclick="event.stopPropagation();">
                        ${escapeHtml(row.worker)}
                    </a>
                </td>
                <td style="padding: 10px;">${escapeHtml(bucket)}</td>
                <td style="padding: 10px; color: #e65100;">${escapeHtml(row.reason)}</td>
                <td style="padding: 10px; text-align: right;">$${row.cash_tips.toFixed(2)}</td>
                <td style="padding: 10px; text-align: right;">$${row.credit_tips.toFixed(2)}</td>
                <td style="padding: 10px; text-align: right; font-weight: 600;">$${total.toFixed(2)}</td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    container.innerHTML = html;
}


// =====================
// FETCH FUNCTIONS
// =====================

// Set default dates for fetch page
function initFetchPage() {
    const today = new Date().toISOString().split('T')[0];
    const startDate = new Date();
    startDate.setDate(startDate.getDate() - 7);
    const startDateStr = startDate.toISOString().split('T')[0];
    
    const startInput = document.getElementById('fetchStartDate');
    const endInput = document.getElementById('fetchEndDate');
    
    if (startInput) startInput.value = startDateStr;
    if (endInput) endInput.value = today;
    loadAutoFetchStatus();
}

async function loadAutoFetchStatus() {
    const autoEl = document.getElementById('autoFetchIntervalValue');
    const laborEl = document.getElementById('laborWatchIntervalValue');
    const laborLastEl = document.getElementById('laborWatchLastChangeValue');
    const laborInput = document.getElementById('laborWatchIntervalInput');
    if (!autoEl) return;

    autoEl.textContent = 'Loading...';
    if (laborEl) laborEl.textContent = 'Loading...';
    if (laborLastEl) laborLastEl.textContent = 'Loading...';
    try {
        const response = await fetch(`${LOCAL_API}/admin/auto-fetch/status`);
        if (!response.ok) {
            throw new Error('Failed to load status');
        }
        const data = await response.json();
        if (!data.enabled) {
            autoEl.textContent = 'Disabled';
            if (laborEl) laborEl.textContent = 'Disabled';
            if (laborLastEl) laborLastEl.textContent = 'Unknown';
            return;
        }
        if (typeof data.interval_minutes === 'number' && data.interval_minutes > 0) {
            autoEl.textContent = `Every ${data.interval_minutes} minutes (full sweep)`;
        } else if (typeof data.interval_hours === 'number' && data.interval_hours > 0) {
            autoEl.textContent = `Every ${data.interval_hours} hours (full sweep)`;
        } else {
            autoEl.textContent = 'Enabled';
        }
        const fast = data.fast_fetch || {};
        if (fast.enabled && typeof fast.interval_minutes === 'number' && fast.interval_minutes > 0) {
            autoEl.textContent += ` · every ${fast.interval_minutes} min (recent days)`;
        }

        const labor = data.labor_watch || {};
        if (laborEl) {
            if (typeof labor.interval_minutes === 'number' && labor.interval_minutes > 0) {
                laborEl.textContent = `Every ${labor.interval_minutes} minute(s)`;
            } else {
                laborEl.textContent = 'Unavailable';
            }
        }
        if (laborInput && typeof labor.interval_minutes === 'number' && labor.interval_minutes > 0) {
            laborInput.value = String(labor.interval_minutes);
        }
        if (laborLastEl) {
            const lastAt = labor.last_change_at || '';
            const summary = labor.last_change_summary || '';
            laborLastEl.textContent = lastAt ? `${lastAt}${summary ? ` (${summary})` : ''}` : 'No changes detected yet';
        }
    } catch (error) {
        autoEl.textContent = 'Unavailable';
        if (laborEl) laborEl.textContent = 'Unavailable';
        if (laborLastEl) laborLastEl.textContent = 'Unavailable';
    }
}

async function triggerFetchNow() {
    const btn = document.getElementById('fetchNowBtn');
    const statusEl = document.getElementById('fetchNowStatus');
    if (btn) btn.loading = true;
    if (statusEl) statusEl.textContent = 'Starting fetch...';
    try {
        const response = await fetch(`${LOCAL_API}/admin/auto-fetch/trigger`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lookback_days: 1 })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.message || data.error || 'Failed to start fetch');
        }
        if (statusEl) {
            statusEl.textContent = data.already_running
                ? 'A fetch is already running — waiting for it to finish...'
                : 'Fetching latest data from Toast...';
        }

        // Poll status until the run completes, then confirm.
        const startedAt = Date.now();
        const poll = setInterval(async () => {
            try {
                const resp = await fetch(`${LOCAL_API}/admin/auto-fetch/status`);
                const status = await resp.json();
                if (!status.running && Date.now() - startedAt > 4000) {
                    clearInterval(poll);
                    if (btn) btn.loading = false;
                    const secs = Math.round((Date.now() - startedAt) / 1000);
                    if (statusEl) statusEl.textContent = `Done — data refreshed (${secs}s). Reload the page you were on.`;
                    showToast('Toast data refreshed', 'success');
                } else if (Date.now() - startedAt > 10 * 60 * 1000) {
                    clearInterval(poll);
                    if (btn) btn.loading = false;
                    if (statusEl) statusEl.textContent = 'Still running in background — check back shortly.';
                }
            } catch (e) {
                // keep polling; transient errors are fine
            }
        }, 4000);
    } catch (error) {
        if (btn) btn.loading = false;
        if (statusEl) statusEl.textContent = `Error: ${error.message}`;
        showToast(`Fetch failed: ${error.message}`, 'danger');
    }
}

async function saveLaborWatchInterval() {
    const input = document.getElementById('laborWatchIntervalInput');
    const minutes = parseInt(input?.value || '1', 10);
    if (!Number.isFinite(minutes) || minutes < 1 || minutes > 60) {
        showToast('Labor watch interval must be between 1 and 60 minutes', 'warning');
        return;
    }
    try {
        const resp = await fetch(`${LOCAL_API}/admin/labor-watch/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interval_minutes: minutes })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Failed to save interval');
        showToast(`Labor watch interval set to ${data.interval_minutes} minute(s)`, 'success');
        await loadAutoFetchStatus();
    } catch (e) {
        showToast(e.message || 'Failed to save labor interval', 'error');
    }
}

// Select all endpoints
function selectAllFetchEndpoints() {
    const select = document.getElementById('fetchEndpoints');
    if (select) {
        select.value = ['time_entries', 'employees', 'jobs', 'shifts', 'orders', 'cash_entries', 'deposits', 'sales_categories', 'revenue_centers'];
    }
}

// Clear all endpoints
function clearFetchEndpoints() {
    const select = document.getElementById('fetchEndpoints');
    if (select) {
        select.value = [];
    }
}

// Fetch data from Toast API
async function fetchToastData() {
    const startDate = document.getElementById('fetchStartDate')?.value;
    const endDate = document.getElementById('fetchEndDate')?.value;
    const endpointsSelect = document.getElementById('fetchEndpoints');
    
    if (!startDate || !endDate) {
        showToast('Please select start and end dates', 'warning');
        return;
    }
    
    const selectedEndpoints = endpointsSelect?.value || [];
    if (selectedEndpoints.length === 0) {
        showToast('Please select at least one endpoint', 'warning');
        return;
    }
    
    // Handle "all" selection
    let endpoints = selectedEndpoints;
    if (selectedEndpoints.includes('all')) {
        endpoints = ['time_entries', 'employees', 'jobs', 'shifts', 'orders', 'cash_entries', 'deposits', 'sales_categories', 'revenue_centers'];
    }
    
    // Show results section
    const resultsDiv = document.getElementById('fetchResults');
    const progressDiv = document.getElementById('fetchProgress');
    const resultsBody = document.getElementById('fetchResultsBody');
    const statusBadge = document.getElementById('fetchStatusBadge');
    
    if (resultsDiv) resultsDiv.style.display = 'block';
    if (progressDiv) progressDiv.style.display = 'block';
    if (statusBadge) {
        statusBadge.textContent = 'Fetching...';
        statusBadge.variant = 'primary';
    }
    
    // Clear previous results
    if (resultsBody) resultsBody.innerHTML = '';
    
    const results = [];
    const startTime = Date.now();
    
    // Fetch each endpoint sequentially
    for (let i = 0; i < endpoints.length; i++) {
        const endpoint = endpoints[i];
        const progressText = document.getElementById('fetchProgressText');
        const progressBar = document.getElementById('fetchProgressBar');
        
        if (progressText) progressText.textContent = `Fetching ${endpoint}... (${i + 1}/${endpoints.length})`;
        if (progressBar) progressBar.value = ((i + 1) / endpoints.length) * 100;
        
        try {
            const response = await fetch(`${LOCAL_API}/fetch/toast`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    endpoint: endpoint,
                    start_date: startDate,
                    end_date: endDate
                })
            });
            
            const data = await response.json();
            
            results.push({
                endpoint: endpoint,
                status: response.ok ? 'success' : 'error',
                records: data.count || data.records || 0,
                duration: data.duration_ms || '-',
                message: data.message || (response.ok ? 'Fetched successfully' : data.error || 'Unknown error')
            });
            
            // Add row to table
            if (resultsBody) {
                const row = document.createElement('tr');
                row.style.borderBottom = '1px solid #eee';
                row.innerHTML = `
                    <td style="padding: 10px; font-weight: 500;">${escapeHtml(endpoint)}</td>
                    <td style="padding: 10px;">
                        <sl-badge variant="${response.ok ? 'success' : 'danger'}">
                            ${response.ok ? 'Success' : 'Error'}
                        </sl-badge>
                    </td>
                    <td style="padding: 10px; text-align: right;">${data.count || data.records || 0}</td>
                    <td style="padding: 10px; text-align: right;">${data.duration_ms ? data.duration_ms + 'ms' : '-'}</td>
                    <td style="padding: 10px; color: ${response.ok ? '#666' : '#d32f2f'};">${escapeHtml(data.message || data.error || '')}</td>
                `;
                resultsBody.appendChild(row);
            }
            
        } catch (error) {
            results.push({
                endpoint: endpoint,
                status: 'error',
                records: 0,
                duration: '-',
                message: error.message || 'Network error'
            });
            
            if (resultsBody) {
                const row = document.createElement('tr');
                row.style.borderBottom = '1px solid #eee';
                row.innerHTML = `
                    <td style="padding: 10px; font-weight: 500;">${escapeHtml(endpoint)}</td>
                    <td style="padding: 10px;">
                        <sl-badge variant="danger">Error</sl-badge>
                    </td>
                    <td style="padding: 10px; text-align: right;">0</td>
                    <td style="padding: 10px; text-align: right;">-</td>
                    <td style="padding: 10px; color: #d32f2f;">${escapeHtml(error.message || 'Network error')}</td>
                `;
                resultsBody.appendChild(row);
            }
        }
    }
    
    const totalTime = Date.now() - startTime;
    
    if (progressDiv) progressDiv.style.display = 'none';
    if (statusBadge) {
        const successCount = results.filter(r => r.status === 'success').length;
        const errorCount = results.length - successCount;
        
        if (errorCount === 0) {
            statusBadge.textContent = `Complete (${successCount}/${results.length})`;
            statusBadge.variant = 'success';
            showToast(`Fetched ${successCount} endpoints in ${totalTime}ms`, 'success');
        } else {
            statusBadge.textContent = `Partial (${successCount}/${results.length})`;
            statusBadge.variant = 'warning';
            showToast(`${errorCount} endpoints failed`, 'warning');
        }
    }
}

async function syncToJaq() {
    const statusDiv = document.getElementById('syncJaqStatus');
    if (!statusDiv) return;
    
    statusDiv.style.display = 'block';
    statusDiv.innerHTML = `
        <div style="display: flex; align-items: center; gap: 12px; background: rgba(255,255,255,0.2); padding: 16px; border-radius: 8px;">
            <sl-spinner style="font-size: 24px;"></sl-spinner>
            <div>
                <div style="font-weight: 600;">Syncing data to JAQ...</div>
                <div style="font-size: 0.85rem; opacity: 0.8;">This may take a minute</div>
            </div>
        </div>
    `;
    
    try {
        const response = await fetch(`${LOCAL_API}/sync/jaq`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (data.success) {
            statusDiv.innerHTML = `
                <div style="background: rgba(76, 175, 80, 0.3); padding: 16px; border-radius: 8px; border: 1px solid rgba(76, 175, 80, 0.5);">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                        <sl-icon name="check-circle" style="font-size: 24px; color: #4caf50;"></sl-icon>
                        <span style="font-weight: 600;">Sync Complete!</span>
                    </div>
                    <div style="font-size: 0.9rem; opacity: 0.9;">
                        ${data.files_synced} files synced to JAQ data lake.<br>
                        JAQ Status: ${data.jaq_status}
                    </div>
                </div>
            `;
            showToast(`Synced ${data.files_synced} files to JAQ`, 'success');
        } else {
            statusDiv.innerHTML = `
                <div style="background: rgba(244, 67, 54, 0.3); padding: 16px; border-radius: 8px; border: 1px solid rgba(244, 67, 54, 0.5);">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                        <sl-icon name="exclamation-triangle" style="font-size: 24px; color: #f44336;"></sl-icon>
                        <span style="font-weight: 600;">Sync Failed</span>
                    </div>
                    <div style="font-size: 0.9rem; opacity: 0.9;">${escapeHtml(data.error || 'Unknown error')}</div>
                </div>
            `;
            showToast('Sync failed: ' + (data.error || 'Unknown error'), 'danger');
        }
    } catch (error) {
        statusDiv.innerHTML = `
            <div style="background: rgba(244, 67, 54, 0.3); padding: 16px; border-radius: 8px; border: 1px solid rgba(244, 67, 54, 0.5);">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                    <sl-icon name="exclamation-triangle" style="font-size: 24px; color: #f44336;"></sl-icon>
                    <span style="font-weight: 600;">Sync Error</span>
                </div>
                <div style="font-size: 0.9rem; opacity: 0.9;">${escapeHtml(error.message)}</div>
            </div>
        `;
        showToast('Sync error: ' + error.message, 'danger');
    }
}
