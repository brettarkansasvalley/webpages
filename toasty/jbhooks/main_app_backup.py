#!/usr/bin/env python3
"""
Main application class for the Restaurant Tip Distribution System
"""
#main_app.py
import tkinter as tk
from tkinter import ttk, messagebox
import json
from datetime import datetime

from config import (
    UNIFORM_FONT, UNIFORM_BOLD, TREEVIEW_ROW_HEIGHT,
    SCROLLBAR_WIDTH, PAD_X, PAD_Y, ADMIN_PASSWORD, MAX_LOGIN_ATTEMPTS,
    WINDOW_GEOMETRY, BUCKETS, CASH_DRAWERS, BUCKET_DISPLAY_NAMES
)
from database import DatabaseManager
from tip_calculator import TipCalculator
from ui_popups import (
    NumericKeyboardPopup, AlphaKeyboardPopup, ReviewPopup, PasswordPopup,
    RoleSelectionPopup, PayoutWorkerSelectionPopup, WorkerSelectionPopup,
    BartenderSelectionPopup
)


class TipDistributionTouchApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Restaurant Tip Distribution - Touch Interface")
        self.geometry(WINDOW_GEOMETRY)
        self.attributes('-fullscreen', True)
        self.bind('<Escape>', lambda e: self.destroy())

        # Initialize components
        self.db_manager = DatabaseManager()
        self.conn = self.db_manager.conn  # For backward compatibility
        self.tip_calculator = TipCalculator()

        # Admin settings
        self.admin_password = ADMIN_PASSWORD
        self.login_attempts = 0
        self.max_login_attempts = MAX_LOGIN_ATTEMPTS
        self.admin_access_granted = False
        self.previous_tab = 0

        # Configure styles
        self._configure_styles()

        # Initialize data structures
        self.buckets = BUCKETS.copy()
        
        # Server Tab Variables
        self.selected_bucket = tk.StringVar(value="am_bar")
        self.selected_worker = tk.StringVar()
        self.bartips_var = tk.DoubleVar()
        self.servertips_var = tk.DoubleVar()
        self.expotips_var = tk.DoubleVar()
        self.runnertips_var = tk.DoubleVar()
        self.cashtips_var = tk.DoubleVar()
        self.creditcardtip_var = tk.DoubleVar()
        self.gratuity_var = tk.DoubleVar()
        self.netsales_var = tk.DoubleVar()
        self.gross_tip_percentage_var = tk.StringVar(value="Gross Tip %: N/A")
        self.owed_to_server_var = tk.DoubleVar()
        self.owed_to_restaurant_var = tk.DoubleVar()
        self.bartender1_var = tk.StringVar()
        self.bartender2_var = tk.StringVar()
        self.bartender3_var = tk.StringVar()

        # Bartender Tab Variables
        self.bt_selected_bucket = tk.StringVar(value="am_bar")
        self.bt_bartender1_var = tk.StringVar()
        self.bt_bartender2_var = tk.StringVar()
        self.bt_bartender3_var = tk.StringVar()
        self.bt_bartips_var = tk.DoubleVar()
        self.bt_servertips_var = tk.DoubleVar()
        self.bt_expotips_var = tk.DoubleVar()
        self.bt_runnertips_var = tk.DoubleVar()
        self.bt_cashtips_var = tk.DoubleVar()
        self.bt_creditcardtip_var = tk.DoubleVar()
        self.bt_netsales_var = tk.DoubleVar()
        self.bt_gross_tip_percentage_var = tk.StringVar(value="Gross Tip %: 0.00%")
        self.bt_cash_in_drawer_var = tk.DoubleVar()
        self.bt_owed_to_bar_var = tk.DoubleVar()
        self.bt_owed_to_restaurant_var = tk.DoubleVar()
        
        # Common Variables
        self.new_worker_name = tk.StringVar()
        self.workers = self.db_manager.load_workers()
        self.payout_tip_widgets = {}
        self.bt_payout_tip_widgets = {}
        self.admin_cashbox_amount_var = tk.DoubleVar()
        self.admin_cashbox_reason_var = tk.StringVar()
        self.admin_cashbox_drawer_var = tk.StringVar()
        self.payouts_bucket = tk.StringVar(value="am_bar")
        self.worker_assignments = {}
        self.worker_tips = {}
        self.updating_from_code = False
        self.worker_roles_var = tk.StringVar(value="Select a worker to see their roles.")
        self.cash_drawers = CASH_DRAWERS
        self.selected_cash_drawer = tk.StringVar(value=self.cash_drawers[0])

        # Load data from database
        self._load_assignments_from_database()
        self._recalculate_all_data_from_source()

        # Set up variable traces
        self._setup_traces()

        # Initialize UI
        self.admin_tab_initialized = False
        self.setup_ui()

    def _configure_styles(self):
        """Configure TTK styles"""
        s = ttk.Style()
        s.configure("TButton", padding=6, font=UNIFORM_FONT)
        s.configure("Treeview", rowheight=TREEVIEW_ROW_HEIGHT)
        s.configure("Treeview.Heading", font=UNIFORM_FONT, padding=4)
        s.configure("TScrollbar", width=SCROLLBAR_WIDTH)
        s.configure("TCombobox", font=UNIFORM_FONT)
        s.configure("TCheckbutton", font=UNIFORM_FONT)

        s.configure("Uniform.TLabel", font=UNIFORM_FONT)
        s.configure("UniformBold.TLabel", font=UNIFORM_BOLD)
        s.configure("Uniform.TEntry", font=UNIFORM_FONT)
        s.configure("UniformBold.TEntry", font=UNIFORM_BOLD)
        s.configure("Uniform.TButton", font=UNIFORM_FONT, padding=6)
        s.configure("UniformBold.TButton", font=UNIFORM_BOLD, padding=8)
        s.configure("Uniform.TCombobox", font=UNIFORM_FONT)
        s.configure("Uniform.TLabelframe", font=UNIFORM_BOLD, padding=6)
        s.configure("Uniform.TLabelframe.Label", font=UNIFORM_BOLD)

    def _setup_traces(self):
        """Set up variable traces"""
        # Traces for Server Tab
        self.selected_worker.trace_add("write", self.on_worker_change)
        self.selected_bucket.trace_add("write", self.on_bucket_change)
        self.owed_to_server_var.trace_add("write", self.on_owed_to_server_change)
        self.owed_to_restaurant_var.trace_add("write", self.on_owed_to_restaurant_change)

        # Traces for Bartender Tab
        self.bt_selected_bucket.trace_add("write", self.on_bt_bucket_change)
        self.bt_cash_in_drawer_var.trace_add("write", self.bt_handle_data_update)
        self.bt_owed_to_bar_var.trace_add("write", self.bt_handle_data_update)
        self.bt_owed_to_restaurant_var.trace_add("write", self.bt_handle_data_update)
        
        self.payouts_bucket.trace_add("write", self.on_payouts_bucket_change)

    def _load_assignments_from_database(self):
        """Load worker assignments from database"""
        self.worker_assignments = self.db_manager.load_assignments_from_database()

    def _recalculate_all_data_from_source(self):
        """Recalculate all data from database"""
        self.worker_tips = self.db_manager.recalculate_all_data_from_source(self.buckets)
        for bucket_id in self.buckets:
            self.calculate_bucket_totals(bucket_id)

    def calculate_bucket_totals(self, bucket_id):
        """Calculate totals for a bucket using the tip calculator"""
        self.tip_calculator.calculate_bucket_totals(bucket_id, self.worker_tips, self.worker_assignments)

    def _get_drawer_for_bucket(self, bucket):
        """Get drawer for bucket using tip calculator"""
        return self.tip_calculator.get_drawer_for_bucket(bucket)

    def load_workers(self):
        """Load workers from database"""
        return self.db_manager.load_workers()

    def add_worker(self, name):
        """Add worker to database"""
        result = self.db_manager.add_worker(name)
        if result:
            self.workers = self.db_manager.load_workers()
        return result

    def save_transaction(self, worker_name, bucket, tips, payouts):
        """Save transaction to database"""
        self.db_manager.save_transaction(worker_name, bucket, tips, payouts)
        self.refresh_all_reports()

    def get_worker_roles(self, worker_name):
        """Get worker roles from database"""
        return self.db_manager.get_worker_roles(worker_name)

    def update_worker_roles(self, worker_name, roles):
        """Update worker roles in database"""
        self.db_manager.update_worker_roles(worker_name, roles)
        self.refresh_workers_list()
        self.refresh_all_reports()
        # Refresh the roles display for the currently selected worker
        self.on_worker_selection_change()

    # UI Creation Methods (these would be the same as in the original file)
    def setup_ui(self):
        """Set up the main UI"""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        style = ttk.Style()
        style.configure('TNotebook.Tab', font=("Helvetica", 12, "bold"), padding=[15, 5])

        # Create tabs
        self.tip_input_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.tip_input_frame, text="Server Tip Input")
        self.create_server_tip_input_tab()

        self.bartender_input_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.bartender_input_frame, text="Bartender Tip Input")
        self.create_bartender_input_tab()

        self.payouts_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.payouts_frame, text="Payouts")
        self.create_payouts_tab()

        self.server_report_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.server_report_frame, text="Server Report")
        self.create_server_report_tab()

        self.bartender_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.bartender_frame, text="Bartend Report")
        self.create_bartender_report_tab()

        self.workers_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.workers_frame, text="Workers")
        self.create_workers_tab()

        self.cashbox_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.cashbox_frame, text="Cashbox")
        self.create_cashbox_tab()

        self.report_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.report_frame, text="Report")
        self.create_report_tab()
        
        self.admin_frame = ttk.Frame(self.notebook, padding="6")
        self.notebook.add(self.admin_frame, text="Admin")
        
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

    # Essential UI creation methods
    def create_server_tip_input_tab(self):
        """Create server tip input tab"""
        master_frame = ttk.Frame(self.tip_input_frame)
        master_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(master_frame)
        scrollbar = ttk.Scrollbar(master_frame, orient="vertical", command=canvas.yview, style="TScrollbar")
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        def frame_width(event): canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind('<Configure>', frame_width)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        selection_frame = ttk.Frame(scrollable_frame)
        selection_frame.pack(fill=tk.X, pady=(0, 15), padx=5)

        bucket_frame = ttk.LabelFrame(selection_frame, text="Select Bucket", style="Uniform.TLabelframe")
        bucket_frame.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        bucket_buttons_container = ttk.Frame(bucket_frame)
        bucket_buttons_container.pack(pady=5, fill=tk.X)
        self.tip_input_bucket_buttons = {}
        buckets = BUCKET_DISPLAY_NAMES
        for i, (bid, bname) in enumerate(buckets):
            btn = ttk.Button(bucket_buttons_container, text=bname, command=lambda b=bid: self.select_tip_input_bucket(b))
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3, ipady=6)
            self.tip_input_bucket_buttons[bid] = btn

        worker_frame = ttk.LabelFrame(selection_frame, text="Select Server", style="Uniform.TLabelframe")
        worker_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.server_worker_button = ttk.Button(worker_frame, text="Select Server", command=self.show_worker_selection_popup_server, style="UniformBold.TButton")
        self.server_worker_button.pack(pady=5, fill=tk.X, ipady=3)

        selected_server_label = ttk.Label(worker_frame, textvariable=self.selected_worker, style="UniformBold.TLabel", justify=tk.CENTER)
        selected_server_label.pack(pady=(2,5))

        content_frame = ttk.Frame(scrollable_frame)
        content_frame.pack(pady=(0, 10), padx=5)
        content_frame.columnconfigure((0, 1), weight=1)

        main_figures_frame = ttk.LabelFrame(content_frame, text="Main Figures", style="Uniform.TLabelframe")
        main_figures_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.create_popup_entry(main_figures_frame, "Cash Tips:", self.cashtips_var, 0, self._handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Non-cash Tips:", self.creditcardtip_var, 1, self._handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Gratuity:", self.gratuity_var, 2, self._handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Net Sales:", self.netsales_var, 3, self._handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Owed to Server:", self.owed_to_server_var, 4, self._handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Owed to Restaurant:", self.owed_to_restaurant_var, 5, self._handle_data_update, ipady=4)
        ttk.Label(main_figures_frame, textvariable=self.gross_tip_percentage_var, style="UniformBold.TLabel").grid(row=6, column=0, columnspan=2, pady=6)

        self.tip_frame = ttk.LabelFrame(content_frame, text="Add Tips for Payout", style="Uniform.TLabelframe")
        self.tip_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.payout_tip_widgets.clear()
        self.payout_tip_widgets['bartips'] = self.create_popup_entry(self.tip_frame, "Bar Tips:", self.bartips_var, 0, self._handle_data_update, ipady=4)
        self.payout_tip_widgets['servertips'] = self.create_popup_entry(self.tip_frame, "Busser Tips:", self.servertips_var, 1, self._handle_data_update, ipady=4)
        self.payout_tip_widgets['expotips'] = self.create_popup_entry(self.tip_frame, "Expo Tips:", self.expotips_var, 2, self._handle_data_update, ipady=4)
        self.payout_tip_widgets['runnertips'] = self.create_popup_entry(self.tip_frame, "Runner Tips:", self.runnertips_var, 3, self._handle_data_update, ipady=4)
        
        action_button_frame = ttk.Frame(scrollable_frame)
        action_button_frame.pack(fill=tk.X, pady=10, padx=5)
        action_button_frame.columnconfigure((0, 1), weight=1)
        
        review_button = ttk.Button(action_button_frame, text="Review", command=self.show_review_popup_server, style="UniformBold.TButton")
        review_button.grid(row=0, column=0, sticky=tk.EW, padx=(0, 5), ipady=5)
        clear_button = ttk.Button(action_button_frame, text="Clear", command=self.clear_current_tip_input, style="Uniform.TButton")
        clear_button.grid(row=0, column=1, sticky=tk.EW, padx=(5, 0), ipady=5)

        self.select_tip_input_bucket(self.selected_bucket.get())
        self.on_bucket_change()

    def create_bartender_input_tab(self):
        """Create bartender input tab"""
        master_frame = ttk.Frame(self.bartender_input_frame)
        master_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(master_frame)
        scrollbar = ttk.Scrollbar(master_frame, orient="vertical", command=canvas.yview, style="TScrollbar")
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        def frame_width(event): canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind('<Configure>', frame_width)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        selection_frame = ttk.Frame(scrollable_frame)
        selection_frame.pack(fill=tk.X, pady=(0, 15), padx=5)

        bucket_frame = ttk.LabelFrame(selection_frame, text="Select Bar", style="Uniform.TLabelframe")
        bucket_frame.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        bucket_buttons_container = ttk.Frame(bucket_frame)
        bucket_buttons_container.pack(pady=5, fill=tk.X)
        self.bt_tip_input_bucket_buttons = {}
        buckets = [("am_bar", "AM"), ("westwing", "West Wing"), ("sunset", "Sunset")]
        for i, (bid, bname) in enumerate(buckets):
            btn = ttk.Button(bucket_buttons_container, text=bname, command=lambda b=bid: self.bt_select_tip_input_bucket(b))
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3, ipady=6)
            self.bt_tip_input_bucket_buttons[bid] = btn

        worker_frame = ttk.LabelFrame(selection_frame, text="Select Bartenders", style="Uniform.TLabelframe")
        worker_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(worker_frame, text="Select Bartenders", command=self.bt_show_worker_selection_popup, style="UniformBold.TButton").pack(pady=5, fill=tk.X, ipady=3)
        self.bt_selected_bartender_labels = []
        for i in range(3):
            lbl = ttk.Label(worker_frame, text="", style="Uniform.TLabel")
            lbl.pack(anchor="w", padx=5)
            self.bt_selected_bartender_labels.append(lbl)

        content_frame = ttk.Frame(scrollable_frame)
        content_frame.pack(pady=(0, 10), padx=5)
        content_frame.columnconfigure((0, 1), weight=1)

        main_figures_frame = ttk.LabelFrame(content_frame, text="Main Figures", style="Uniform.TLabelframe")
        main_figures_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.create_popup_entry(main_figures_frame, "Cash Tips:", self.bt_cashtips_var, 0, self.bt_handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Non-cash Tips:", self.bt_creditcardtip_var, 1, self.bt_handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Net Sales:", self.bt_netsales_var, 2, self.bt_handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Cash in Drawer:", self.bt_cash_in_drawer_var, 3, self.bt_handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Owed to bar:", self.bt_owed_to_bar_var, 4, self.bt_handle_data_update, ipady=4)
        self.create_popup_entry(main_figures_frame, "Owed to Restaurant:", self.bt_owed_to_restaurant_var, 5, self.bt_handle_data_update, ipady=4)
        ttk.Label(main_figures_frame, textvariable=self.bt_gross_tip_percentage_var, style="UniformBold.TLabel").grid(row=6, column=0, columnspan=2, pady=6)

        self.bt_tip_frame = ttk.LabelFrame(content_frame, text="Add Tips for Payout", style="Uniform.TLabelframe")
        self.bt_tip_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.bt_payout_tip_widgets.clear()
        self.bt_payout_tip_widgets['servertips'] = self.create_popup_entry(self.bt_tip_frame, "Busser Tips:", self.bt_servertips_var, 1, self.bt_handle_data_update, ipady=4)
        self.bt_payout_tip_widgets['expotips'] = self.create_popup_entry(self.bt_tip_frame, "Expo Tips:", self.bt_expotips_var, 2, self.bt_handle_data_update, ipady=4)
        self.bt_payout_tip_widgets['runnertips'] = self.create_popup_entry(self.bt_tip_frame, "Runner Tips:", self.bt_runnertips_var, 3, self.bt_handle_data_update, ipady=4)
        
        action_button_frame = ttk.Frame(scrollable_frame)
        action_button_frame.pack(fill=tk.X, pady=10, padx=5)
        action_button_frame.columnconfigure((0, 1), weight=1)
        
        review_button = ttk.Button(action_button_frame, text="Review", command=self.bt_show_review_popup, style="UniformBold.TButton")
        review_button.grid(row=0, column=0, sticky=tk.EW, padx=(0, 5), ipady=5)
        clear_button = ttk.Button(action_button_frame, text="Clear", command=self.bt_clear_current_tip_input, style="Uniform.TButton")
        clear_button.grid(row=0, column=1, sticky=tk.EW, padx=(5, 0), ipady=5)

        self.bt_select_tip_input_bucket(self.bt_selected_bucket.get())
        self.on_bt_bucket_change()

    def create_payouts_tab(self):
        """Create payouts tab"""
        bucket_frame = ttk.LabelFrame(self.payouts_frame, text="Select Bucket", style="Uniform.TLabelframe")
        bucket_frame.pack(fill=tk.X, pady=(0, 10))
        bucket_buttons_frame = ttk.Frame(bucket_frame)
        bucket_buttons_frame.pack(fill=tk.X, pady=5)
        self.bucket_buttons = {}
        for i, (bid, bname) in enumerate([("am_bar", "AM"), ("eastwing", "East Wing"), ("westwing", "West Wing"), ("sunset", "Sunset")]):
            btn = ttk.Button(bucket_buttons_frame, text=bname, command=lambda b=bid: self.select_payout_bucket(b), style="Uniform.TButton")
            btn.grid(row=0, column=i, padx=5, pady=5, sticky="ew", ipady=10)
            self.bucket_buttons[bid] = btn
            bucket_buttons_frame.grid_columnconfigure(i, weight=1)
        self.payouts_display_frame = ttk.LabelFrame(self.payouts_frame, text="Payout Assignments", style="Uniform.TLabelframe")
        self.payouts_display_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.current_payout_bucket = "am_bar"
        self.create_touch_payouts_display()

    def create_server_report_tab(self):
        """Create server report tab"""
        main_frame = ttk.Frame(self.server_report_frame, padding="8")
        main_frame.pack(fill=tk.BOTH, expand=True)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(0, 10), fill=tk.X)
        ttk.Button(button_frame, text="Refresh Report", command=self.populate_server_report_tab, style="UniformBold.TButton").pack(side=tk.LEFT, ipady=6)

        ledger_frame = ttk.LabelFrame(main_frame, text="Server Ledger", padding="8", style="Uniform.TLabelframe")
        ledger_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("date", "server", "bucket", "cash_tips", "non_cash_tips", "gratuity", "payout_tips", "net_sales", "tip_perc")
        headings = ("Date", "Server", "Bucket", "Cash Tips", "Non-Cash", "Gratuity", "Payouts", "Net Sales", "Tip %")
        self.server_report_tree = self.create_report_treeview(ledger_frame, columns=cols, headings=headings)
        
        for col in cols:
            self.server_report_tree.column(col, width=100)
        
        # Add delete button for server records
        delete_frame = ttk.Frame(button_frame)
        delete_frame.pack(side=tk.RIGHT)
        self.delete_server_button = ttk.Button(delete_frame, text="Delete Selected", command=self.delete_selected_server_record, style="Uniform.TButton", state="disabled")
        self.delete_server_button.pack(side=tk.LEFT, padx=(10,0), ipady=6)
        
        self.server_report_tree.bind("<<TreeviewSelect>>", self.on_server_record_select)
        self.populate_server_report_tab()

    def create_bartender_report_tab(self):
        """Create bartender report tab"""
        main_frame = ttk.Frame(self.bartender_frame, padding="8")
        main_frame.pack(fill=tk.BOTH, expand=True)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(0, 10), fill=tk.X)
        ttk.Button(button_frame, text="Refresh Report", command=self.populate_bartender_report_tab, style="UniformBold.TButton").pack(side=tk.LEFT, ipady=6)

        ledger_frame = ttk.LabelFrame(main_frame, text="Bartender Ledger", padding="8", style="Uniform.TLabelframe")
        ledger_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("date", "bartender", "job_title", "bar_name", "cash_tips", "credit_tips", "payout_tips", "net_sales", "tip_perc")
        headings = ("Date", "Bartender", "Job", "Bar", "Cash Tips", "Credit Tips", "Payout Tips", "Net Sales", "Tip %")
        self.bartender_tree = self.create_report_treeview(ledger_frame, columns=cols, headings=headings)
        
        for col in cols:
            self.bartender_tree.column(col, width=100)
        
        # Add delete button for bartender records
        delete_frame = ttk.Frame(button_frame)
        delete_frame.pack(side=tk.RIGHT)
        self.delete_bartender_button = ttk.Button(delete_frame, text="Delete Selected", command=self.delete_selected_bartender_record, style="Uniform.TButton", state="disabled")
        self.delete_bartender_button.pack(side=tk.LEFT, padx=(10,0), ipady=6)
        
        self.bartender_tree.bind("<<TreeviewSelect>>", self.on_bartender_record_select)
        self.populate_bartender_report_tab()

    def create_workers_tab(self):
        """Create workers tab"""
        add_frame = ttk.LabelFrame(self.workers_frame, text="Add New Worker", style="Uniform.TLabelframe")
        add_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(add_frame, text="Worker Name:", style="Uniform.TLabel").grid(row=0, column=0, sticky=tk.W, padx=PAD_X, pady=PAD_Y)
        new_worker_entry = ttk.Entry(add_frame, textvariable=self.new_worker_name, state="readonly", style="Uniform.TEntry", font=UNIFORM_FONT)
        new_worker_entry.grid(row=0, column=1, sticky=tk.EW, padx=PAD_X, pady=PAD_Y, ipady=3)
        new_worker_entry.bind("<Button-1>", lambda ev: self.show_alpha_popup(self.new_worker_name, "Worker Name"))
        ttk.Button(add_frame, text="ADD WORKER", command=self.add_new_worker, style="UniformBold.TButton").grid(row=0, column=2, padx=PAD_X, pady=PAD_Y, ipady=3)
        add_frame.grid_columnconfigure(1, weight=1)

        middle_frame = ttk.Frame(self.workers_frame)
        middle_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        middle_frame.columnconfigure(0, weight=1)
        middle_frame.columnconfigure(1, weight=1)
        middle_frame.rowconfigure(0, weight=1)

        workers_display_frame = ttk.LabelFrame(middle_frame, text="Current Workers", style="Uniform.TLabelframe")
        workers_display_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        canvas = tk.Canvas(workers_display_frame)
        scrollbar = ttk.Scrollbar(workers_display_frame, orient="vertical", command=canvas.yview, style="TScrollbar")
        self.workers_scrollable_frame = ttk.Frame(canvas)
        self.workers_scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.workers_scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.selected_worker_for_deletion = tk.StringVar()
        self.refresh_workers_list()
        
        roles_display_frame = ttk.LabelFrame(middle_frame, text="Assigned Roles", style="Uniform.TLabelframe")
        roles_display_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        
        roles_label = ttk.Label(roles_display_frame, textvariable=self.worker_roles_var, style="Uniform.TLabel", wraplength=350, justify=tk.LEFT, anchor="nw")
        roles_label.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        bottom_frame = ttk.Frame(self.workers_frame)
        bottom_frame.pack(fill=tk.X, pady=(0, 10))
        
        bottom_frame.columnconfigure(0, weight=1)
        bottom_frame.columnconfigure(1, weight=1)

        self.edit_roles_button = ttk.Button(bottom_frame, text="Edit Selected Worker's Roles", command=self.edit_selected_worker_roles, style="Uniform.TButton", state="disabled")
        self.edit_roles_button.grid(row=0, column=0, sticky=tk.EW, ipady=6, padx=(0,5))
        
        ttk.Button(bottom_frame, text="DELETE SELECTED WORKER", command=self.delete_selected_worker, style="Uniform.TButton").grid(row=0, column=1, sticky=tk.EW, ipady=6, padx=(5,0))

        stats_frame = ttk.LabelFrame(self.workers_frame, text="Worker Statistics", style="Uniform.TLabelframe")
        stats_frame.pack(fill=tk.X)
        self.worker_stats_label = ttk.Label(stats_frame, text="", style="Uniform.TLabel")
        self.worker_stats_label.pack(pady=5, padx=10)
        self.update_worker_stats()

    def create_cashbox_tab(self):
        """Create cashbox tab"""
        main_frame = ttk.Frame(self.cashbox_frame, padding="8")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        button_frame_left = ttk.Frame(top_frame)
        button_frame_left.pack(side=tk.LEFT)

        self.cashbox_buttons = {}
        for i, drawer in enumerate(self.cash_drawers):
            btn = ttk.Button(button_frame_left, text=drawer, command=lambda d=drawer: self.select_cash_drawer(d))
            btn.pack(side=tk.LEFT, padx=3, ipady=5)
            self.cashbox_buttons[drawer] = btn
        
        button_frame_right = ttk.Frame(top_frame)
        button_frame_right.pack(side=tk.RIGHT)
        
        self.delete_cashbox_button = ttk.Button(button_frame_right, text="Delete Selected Entry", command=self.delete_cashbox_entry_and_linked_records, style="Uniform.TButton", state="disabled")
        self.delete_cashbox_button.pack(side=tk.LEFT, padx=(5,0), ipady=5)
        
        self.cashbox_balance_var = tk.StringVar(value="Current Balance: $0.00")
        ttk.Label(button_frame_right, textvariable=self.cashbox_balance_var, style="UniformBold.TLabel", font=("Helvetica", 14, "bold")).pack(side=tk.LEFT, padx=(10,0))
        
        ledger_frame = ttk.LabelFrame(main_frame, text="Cashbox Ledger", padding="8", style="Uniform.TLabelframe")
        ledger_frame.pack(fill=tk.BOTH, expand=True)
        self.cashbox_tree = self.create_report_treeview(ledger_frame, columns=("timestamp", "worker", "reason", "amount"), headings=("Timestamp", "Worker", "Reason", "Amount"))
        self.cashbox_tree.column("timestamp", width=160)
        self.cashbox_tree.column("worker", width=150)
        self.cashbox_tree.column("reason", width=250)
        self.cashbox_tree.column("amount", width=120, anchor='e')
        
        self.cashbox_tree.bind("<<TreeviewSelect>>", self.on_cashbox_entry_select)
        
        self.select_cash_drawer(self.cash_drawers[0])

    def create_report_tab(self):
        """Create report tab"""
        main_frame = ttk.Frame(self.report_frame, padding="8")
        main_frame.pack(fill=tk.BOTH, expand=True)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(0, 10), fill=tk.X)
        ttk.Button(button_frame, text="Refresh Report", command=self.populate_report_tab, style="UniformBold.TButton").pack(side=tk.LEFT, padx=(0, 10), ipady=6)
        ttk.Button(button_frame, text="Clear Tip History", command=self.clear_tip_history, style="Uniform.TButton").pack(side=tk.LEFT, ipady=6)
        tip_in_frame = ttk.LabelFrame(main_frame, text="Tip-In History", padding="8", style="Uniform.TLabelframe")
        tip_in_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        payout_frame = ttk.LabelFrame(main_frame, text="Final Payout Report", padding="8", style="Uniform.TLabelframe")
        payout_frame.pack(fill=tk.BOTH, expand=True)
        self.tip_in_tree = self.create_report_treeview(tip_in_frame, columns=("timestamp", "worker", "bucket", "bartips", "servertips", "expotips", "runnertips", "total"), headings=("Timestamp", "Worker", "Bucket", "Bar Tips", "Busser Tips", "Expo Tips", "Runner Tips", "Total Given"))
        self.payout_tree = self.create_report_treeview(payout_frame, columns=("timestamp", "bucket", "destination", "worker", "amount"), headings=("Timestamp", "Bucket", "Payout To", "Worker", "Amount Received"))
        self.populate_report_tab()

    # Event handlers and other essential methods
    def on_worker_change(self, *args):
        """Handle worker selection change to update the UI."""
        worker_name = self.selected_worker.get()
        if worker_name:
            # Acorta nombres largos para que quepan en el botón
            display_name = (worker_name[:15] + '..') if len(worker_name) > 17 else worker_name
        else:
            self.server_worker_button.config(text="Select Server")

    def on_bucket_change(self, *args):
        """Handle bucket selection change"""
        # Update UI based on bucket selection
        pass

    def on_owed_to_server_change(self, *args):
        """Handle owed to server change"""
        # Calculate and update related values
        pass

    def on_owed_to_restaurant_change(self, *args):
        """Handle owed to restaurant change"""
        # Calculate and update related values
        pass

    def on_bt_bucket_change(self, *args):
        """Handle bartender bucket change"""
        bucket = self.bt_selected_bucket.get()
        if not bucket:
            return
        
        # Load existing data for this bucket if any
        self.bt_load_bucket_data(bucket)
        
        # Update UI based on bucket selection
        self.bt_update_ui_for_bucket(bucket)
    
    def bt_load_bucket_data(self, bucket):
        """Load existing bartender data for bucket"""
        # This would load saved data for the bucket
        # For now, just reset to defaults
        pass
    
    def bt_update_ui_for_bucket(self, bucket):
        """Update bartender UI for selected bucket"""
        # Update any bucket-specific UI elements
        pass
    
    def bt_handle_data_update(self, *args):
        """Handle bartender data updates"""
        if self.updating_from_code:
            return
        self.bt_update_gross_tip_percentage()
        self.bt_auto_update_and_save()
    
    def bt_update_gross_tip_percentage(self):
        """Update gross tip percentage for bartender"""
        try:
            cash_tips = self.bt_cashtips_var.get()
            credit_tips = self.bt_creditcardtip_var.get()
            net_sales = self.bt_netsales_var.get()
            
            if net_sales > 0:
                gross_tips = cash_tips + credit_tips
                percentage = (gross_tips / net_sales) * 100
                self.bt_gross_tip_percentage_var.set(f"Gross Tip %: {percentage:.2f}%")
            else:
                self.bt_gross_tip_percentage_var.set("Gross Tip %: 0.00%")
        except:
            self.bt_gross_tip_percentage_var.set("Gross Tip %: 0.00%")
    
    def bt_auto_update_and_save(self):
        """Auto update and save bartender data"""
        try:
            bartenders = [b.get() for b in [self.bt_bartender1_var, self.bt_bartender2_var, self.bt_bartender3_var] if b.get()]
            bucket = self.bt_selected_bucket.get()
            
            if not bartenders or not bucket:
                return
            
            # Collect bartender data
            data = {
                'cashtips': self.bt_cashtips_var.get(),
                'creditcardtip': self.bt_creditcardtip_var.get(),
                'netsales': self.bt_netsales_var.get(),
                'cash_in_drawer': self.bt_cash_in_drawer_var.get(),

                'servertips': self.bt_servertips_var.get(),
                'expotips': self.bt_expotips_var.get(),
                'runnertips': self.bt_runnertips_var.get()
            }
            
            # Save for each bartender
            for bartender in bartenders:
                if bartender not in self.bt_worker_tips:
                    self.bt_worker_tips[bartender] = {}
                if bucket not in self.bt_worker_tips[bartender]:
                    self.bt_worker_tips[bartender][bucket] = {}
                
                self.bt_worker_tips[bartender][bucket] = data
                
                # Save to database
                self.save_transaction(bartender, bucket, data, 'bartender')
            
            # Update bucket totals
            self.bt_calculate_bucket_totals(bucket)
            
        except Exception as e:
            print(f"Error in bt_auto_update_and_save: {e}")
    
    def bt_calculate_bucket_totals(self, bucket):
        """Calculate bartender bucket totals"""
        # Calculate totals for the bucket across all bartenders
        # This would update any summary displays
        pass



    def on_payouts_bucket_change(self, *args):
        """Handle payouts bucket change"""
        # Update payouts display based on bucket selection
        pass

    def on_tab_changed(self, event):
        """Handle tab change"""
        # Handle any necessary updates when switching tabs
        selected_tab = event.widget.index("current")
        
        # Refresh reports when switching to report tabs
        if selected_tab == 3:  # Server Report tab
            self.populate_server_report_tab()
        elif selected_tab == 4:  # Bartender Report tab
            self.populate_bartender_report_tab()
        elif selected_tab == 6:  # Report tab
            self.populate_report_tab()
        elif selected_tab == 7:  # Cashbox tab
            self.populate_cashbox_tab()
        elif selected_tab == 8:  # Admin tab
            if not self.admin_access_granted:
                self.show_password_popup()
                return
            if not self.admin_tab_initialized:
                self.create_admin_tab()
                self.admin_tab_initialized = True

    def create_admin_tab(self):
        """Create admin tab"""
        ttk.Label(self.admin_frame, text="Admin Tab", style="UniformBold.TLabel").pack(pady=20)
        ttk.Label(self.admin_frame, text="Admin functions would be available here.", style="Uniform.TLabel").pack()

    def populate_server_report_tab(self):
        """Populate server report tab"""
        # Refresh server report data
        pass

    def populate_bartender_tab(self):
        """Populate bartender tab"""
        # Refresh bartender report data
        pass

    def populate_cashbox_tab(self):
        """Populate the cashbox tab with data"""
        if not hasattr(self, 'cashbox_tree'):
            return
        for i in self.cashbox_tree.get_children():
            self.cashbox_tree.delete(i)
        
        drawer = self.selected_cash_drawer.get()
        if not drawer: 
            return

        cursor = self.conn.cursor()
        cursor.execute('SELECT id, timestamp, worker_name, reason, amount FROM cashbox_ledger WHERE cash_drawer = ? ORDER BY timestamp DESC', (drawer,))
        
        for db_id, ts, w, r, a in cursor.fetchall():
            try: 
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError: 
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            # CORRECTED: Display the amount directly from the database without inverting the sign
            self.cashbox_tree.insert('', 'end', iid=db_id, values=(dt.strftime('%Y-%m-%d %H:%M:%S'), w, r, f"${a:,.2f}"))
        
        balance = self.conn.cursor().execute('SELECT SUM(amount) FROM cashbox_ledger WHERE cash_drawer = ?', (drawer,)).fetchone()[0] or 0.0
        self.cashbox_balance_var.set(f"Current Balance: ${balance:,.2f}")
        self.on_cashbox_entry_select()

    def populate_admin_tab(self):
        """Populate admin tab"""
        # Refresh admin data
        pass

    def bt_select_tip_input_bucket(self, bucket_id):
        """Select bucket for bartender tip input"""
        self.bt_selected_bucket.set(bucket_id)
        for bid, btn in self.bt_tip_input_bucket_buttons.items():
            btn.configure(style="UniformBold.TButton" if bid == bucket_id else "Uniform.TButton")

    def bt_show_worker_selection_popup(self):
        """Show bartender selection popup"""
        available_workers = self.get_workers_by_role("Bartender")
        
        if not available_workers:
            messagebox.showinfo("No Bartenders Found", "No workers are assigned the 'Bartender' role.\nPlease assign the role on the 'Workers' tab.")
            return
            
        BartenderSelectionPopup(self, available_workers, self.update_selected_bartenders)
    
    def update_selected_bartenders(self, bartenders):
        """Update selected bartenders display"""
        self.bt_bartender1_var.set(bartenders[0] if len(bartenders) > 0 else "")
        self.bt_bartender2_var.set(bartenders[1] if len(bartenders) > 1 else "")
        self.bt_bartender3_var.set(bartenders[2] if len(bartenders) > 2 else "")
        
        for i, lbl in enumerate(self.bt_selected_bartender_labels):
            if i < len(bartenders):
                lbl.config(text=f"• {bartenders[i]}")
            else:
                lbl.config(text="")
        
        self.bt_auto_update_and_save()

    def bt_show_review_popup(self):
        """Show review popup for bartender"""
        bartenders = [b.get() for b in [self.bt_bartender1_var, self.bt_bartender2_var, self.bt_bartender3_var] if b.get()]
        if not bartenders:
            messagebox.showwarning("No Bartenders Selected", "Please select at least one bartender first.")
            return
        
        # Get values and perform validation
        cash_in_drawer = self.bt_cash_in_drawer_var.get()
        owed_to_bar = self.bt_owed_to_bar_var.get()
        owed_to_restaurant = self.bt_owed_to_restaurant_var.get()

        if owed_to_bar > 0 and owed_to_restaurant > 0:
            messagebox.showerror("Input Error", "Please fill out either 'Owed to Bar' or 'Owed to Restaurant', but not both.")
            return

        # This is the amount that will be recorded in the cashbox ledger
        transaction_amount = 0
        calculation_display = ""
        reason = "Bartender cash settlement"
        
        if owed_to_restaurant > 0:
            transaction_amount = cash_in_drawer + owed_to_restaurant
            calculation_display = f"Cash in Drawer + Owed to Restaurant\n"
            calculation_display += f"   = ${cash_in_drawer:.2f} + ${owed_to_restaurant:.2f} = ${transaction_amount:.2f}\n\n"
        else:  # Default to using "Owed to Bar" (which might be 0)
            transaction_amount = cash_in_drawer - owed_to_bar
            calculation_display = f"Cash Settlement = Cash in Drawer - Owed to Bar\n"
            calculation_display += f"   = ${cash_in_drawer:.2f} - ${owed_to_bar:.2f} = ${transaction_amount:.2f}\n\n"
        
        # Calculate total to tipout
        total_to_tipout = (self.bt_servertips_var.get() + 
                          self.bt_expotips_var.get() + 
                          self.bt_runnertips_var.get())
        
        # Create simplified review message
        message = f"Bartenders: {', '.join(bartenders)}\n"
        message += f"Bucket: {self.bt_selected_bucket.get().replace('_', ' ').title()}\n\n"
        
        # Updated message to reflect the new dynamic formula
        message += calculation_display

        message += f"Total to tipout = ${total_to_tipout:.2f}"
        
        ReviewPopup(self, "Review Bartender Transaction", message, transaction_amount, reason, 
                   bartenders[0] if bartenders else "", True, bartenders)

    def bt_clear_current_tip_input(self, confirm=True):
        """Clear bartender tip input"""
        bartenders = [b.get() for b in [self.bt_bartender1_var, self.bt_bartender2_var, self.bt_bartender3_var] if b.get()]
        if not bartenders:
            if confirm: 
                messagebox.showwarning("No Selection", "Please select at least one bartender first.")
            return
        if confirm and not messagebox.askyesno("Confirm Clear", "Clear all inputs for the selected bartenders?"):
            return
        
        # Clear all bartender variables
        vars_to_clear = ['bt_cashtips_var', 'bt_creditcardtip_var', 'bt_netsales_var', 
                         'bt_cash_in_drawer_var', 'bt_owed_to_bar_var',
                         'bt_owed_to_restaurant_var',
                         'bt_servertips_var', 'bt_expotips_var', 'bt_runnertips_var']
        
        self.updating_from_code = True
        for var_name in vars_to_clear:
            getattr(self, var_name).set(0.0)
        
        # Clear bartender selections
        self.update_selected_bartenders([])
        self.updating_from_code = False
        
        if confirm:
            messagebox.showinfo("Cleared", "All inputs have been cleared.")

    def create_popup_entry(self, parent, label_text, variable, row, update_callback, ipady=6):
        """Create a popup entry widget"""
        label = ttk.Label(parent, text=label_text, style="Uniform.TLabel")
        label.grid(row=row, column=0, sticky=tk.W, padx=PAD_X, pady=PAD_Y)
        entry = ttk.Entry(parent, textvariable=variable, state="readonly", style="Uniform.TEntry", font=UNIFORM_FONT, justify='right', width=20)
        entry.grid(row=row, column=1, sticky=tk.W, padx=PAD_X, pady=PAD_Y, ipady=ipady)
        entry.bind("<Button-1>", lambda ev, v=variable: self.show_numeric_popup(v))
        variable.trace('w', update_callback)
        return {'label': label, 'entry': entry}

    def select_tip_input_bucket(self, bucket_id):
        """Select bucket for tip input"""
        self.selected_bucket.set(bucket_id)
        for bid, btn in self.tip_input_bucket_buttons.items():
            btn.configure(style="UniformBold.TButton" if bid == bucket_id else "Uniform.TButton")

    def show_worker_selection_popup_server(self):
        """Show worker selection popup for server tab"""
        # Get workers specifically with the "Server" role.
        available_workers = self.get_workers_by_role("Server")
        
        if not available_workers:
            messagebox.showinfo("No Servers Found", "No workers are assigned the 'Server' role.\nPlease assign the role on the 'Workers' tab.", parent=self)
            return
            
        WorkerSelectionPopup(self, available_workers, self.selected_worker, "Select Server")

    def get_workers_for_bucket(self, bucket):
        """Get workers available for a bucket"""
        # This method is currently not used for the server selection popup.
        # It could be used in the future for more complex role/bucket assignments.
        return self.workers

    def show_review_popup_server(self):
        """Show review popup for server"""
        worker = self.selected_worker.get()
        if not worker:
            messagebox.showwarning("No Worker Selected", "Please select a worker first.")
            return
        
        # Calculate payout tips sum
        payout_tips = (self.bartips_var.get() + self.servertips_var.get() + 
                      self.expotips_var.get() + self.runnertips_var.get())
        
        has_report_data = (
        payout_tips > 0 or
        self.cashtips_var.get() > 0 or
        self.creditcardtip_var.get() > 0 or
        self.gratuity_var.get() > 0 or
        self.netsales_var.get() > 0
        )
        
        # Get owed amounts (these are mutually exclusive)
        owed_to_server = self.owed_to_server_var.get()
        owed_to_restaurant = self.owed_to_restaurant_var.get()
        
        # --- CORRECTED LOGIC ---
        # Create calculation display and determine final result with correct accounting sign
        if owed_to_server > 0:
            # If 'Owed to Server' is filled, calculate net amount
            calculation_result = owed_to_server - payout_tips
            calculation_display = f"Owed to Server ${owed_to_server:.2f} - Payout Tips ${payout_tips:.2f}"
            
            if calculation_result >= 0:
                result_display = f"Owed to Server: ${calculation_result:.2f}"
            else:
                result_display = f"Owed to Restaurant: ${abs(calculation_result):.2f}"
            
            # If house pays server (calc > 0), amount is negative (cash out).
            # If server pays house (calc < 0), amount becomes positive (cash in).
            transaction_amount = -calculation_result
        
        elif owed_to_restaurant > 0:
            # If 'Owed to Restaurant' is filled, calculate total owed to house
            calculation_result = owed_to_restaurant + payout_tips
            calculation_display = f"Owed to Restaurant ${owed_to_restaurant:.2f} + Payout Tips ${payout_tips:.2f}"
            result_display = f"Owed to Restaurant: ${calculation_result:.2f}"
            # This is money entering the cashbox, so it is positive.
            transaction_amount = calculation_result
        
        else:
            # Neither field is filled - standard payout
            calculation_display = f"Payout Tips: ${payout_tips:.2f}"
            result_display = "Standard Payout"
            transaction_amount = 0
        # --- END CORRECTED LOGIC ---

        reason = "Server settlement"
        
        # Create review message
        message = f"Worker: {worker}\n"
        message += f"Bucket: {self.selected_bucket.get().replace('_', ' ').title()}\n"
        message += f"Cash Tips: ${self.cashtips_var.get():.2f}\n"
        message += f"Credit Tips: ${self.creditcardtip_var.get():.2f}\n"
        message += f"Gratuity: ${self.gratuity_var.get():.2f}\n"
        message += f"Net Sales: ${self.netsales_var.get():.2f}\n\n"
        message += f"Calculation: {calculation_display}\n"
        message += f"Result: {result_display}"
        
        ReviewPopup(self, "Review Server Transaction", message, transaction_amount, reason, worker, False, has_report_data=has_report_data)

    def clear_current_tip_input(self, confirm=True):
        """Clear current tip input"""
        worker = self.selected_worker.get()
        if not worker:
            if confirm: 
                messagebox.showwarning("No Selection", "Please select a worker first.")
            return
        if confirm and not messagebox.askyesno("Confirm Clear", f"Clear all inputs for '{worker}'?"):
            return
        
        # Clear all variables
        vars_to_clear = ['cashtips_var', 'creditcardtip_var', 'gratuity_var', 'netsales_var', 
                        'owed_to_server_var', 'owed_to_restaurant_var', 'bartips_var', 
                        'servertips_var', 'expotips_var', 'runnertips_var']
        
        self.updating_from_code = True
        for var_name in vars_to_clear:
            getattr(self, var_name).set(0.0)

        self.selected_worker.set("")
        self.server_worker_button.config(text="Select Server")
        
        self.updating_from_code = False
        
        if confirm:
            messagebox.showinfo("Cleared", "All inputs have been cleared.")

    def _handle_data_update(self, *args):
        """Handle data update for server tab"""
        if self.updating_from_code: 
            return
        self.update_gross_tip_percentage()
        self.auto_update_and_save()

    def update_gross_tip_percentage(self):
        """Update gross tip percentage calculation"""
        try:
            total_tips = self.cashtips_var.get() + self.creditcardtip_var.get() + self.gratuity_var.get()
            net_sales = self.netsales_var.get()
            if net_sales > 0:
                percentage = (total_tips / net_sales) * 100
                self.gross_tip_percentage_var.set(f"Gross Tip %: {percentage:.2f}%")
            else:
                self.gross_tip_percentage_var.set("Gross Tip %: N/A")
        except (ValueError, TypeError, ZeroDivisionError):
            self.gross_tip_percentage_var.set("Gross Tip %: N/A")

    def auto_update_and_save(self):
        """Auto update and save data"""
        try:
            worker = self.selected_worker.get()
            bucket = self.selected_bucket.get()
            if not worker or not bucket: 
                return
            
            # Collect data from variables
            data = {
                'cashtips': self.cashtips_var.get(),
                'creditcardtip': self.creditcardtip_var.get(),
                'gratuity': self.gratuity_var.get(),
                'netsales': self.netsales_var.get(),
                'owed_to_server': self.owed_to_server_var.get(),
                'owed_to_restaurant': self.owed_to_restaurant_var.get(),
                'bartips': self.bartips_var.get(),
                'servertips': self.servertips_var.get(),
                'expotips': self.expotips_var.get(),
                'runnertips': self.runnertips_var.get()
            }
            
            # Update worker tips data
            if worker not in self.worker_tips: 
                self.worker_tips[worker] = {}
            if bucket not in self.worker_tips[worker]: 
                self.worker_tips[worker][bucket] = {}
            self.worker_tips[worker][bucket] = data
            
            # Calculate bucket totals and save
            self.calculate_bucket_totals(bucket)
            self.save_transaction(worker, bucket, data, None)
            
        except Exception as e:
            print(f"Error in auto_update_and_save: {e}")

    def bt_handle_data_update(self, *args):
        """Handle data update for bartender tab"""
        if self.updating_from_code: 
            return
        self.bt_update_gross_tip_percentage()
        self.bt_auto_update_and_save()

    def bt_update_gross_tip_percentage(self):
        """Update gross tip percentage for bartender"""
        try:
            total_tips = self.bt_cashtips_var.get() + self.bt_creditcardtip_var.get()
            net_sales = self.bt_netsales_var.get()
            if net_sales > 0:
                percentage = (total_tips / net_sales) * 100
                self.bt_gross_tip_percentage_var.set(f"Gross Tip %: {percentage:.2f}%")
            else:
                self.bt_gross_tip_percentage_var.set("Gross Tip %: N/A")
        except (ValueError, TypeError, ZeroDivisionError):
            self.bt_gross_tip_percentage_var.set("Gross Tip %: N/A")

    def bt_auto_update_and_save(self):
        """Auto update and save bartender data"""
        try:
            bartenders = [b.get() for b in [self.bt_bartender1_var, self.bt_bartender2_var, self.bt_bartender3_var] if b.get()]
            bucket = self.bt_selected_bucket.get()
            if not bartenders or not bucket: 
                return

            # Collect bartender data
            data = {
                'cashtips': self.bt_cashtips_var.get(),
                'creditcardtip': self.bt_creditcardtip_var.get(),
                'netsales': self.bt_netsales_var.get(),
                'cash_in_drawer': self.bt_cash_in_drawer_var.get(),

                'servertips': self.bt_servertips_var.get(),
                'expotips': self.bt_expotips_var.get(),
                'runnertips': self.bt_runnertips_var.get()
            }

            # Update data for each bartender
            for worker in bartenders:
                if worker not in self.worker_tips: 
                    self.worker_tips[worker] = {}
                if bucket not in self.worker_tips[worker]: 
                    self.worker_tips[worker][bucket] = {}
                self.worker_tips[worker][bucket] = data

            self.calculate_bucket_totals(bucket)
            # Save to database for each bartender
            for worker in bartenders:
                self.save_transaction(worker, bucket, data, 'bartender')
            
        except Exception as e:
            print(f"Error in bt_auto_update_and_save: {e}")

    # Additional methods for popup interactions
    def show_numeric_popup(self, target_var):
        """Show numeric keyboard popup"""
        NumericKeyboardPopup(self, target_var)

    def show_alpha_popup(self, target_var, label="Enter Name"):
        """Show alpha keyboard popup"""
        AlphaKeyboardPopup(self, target_var, label)

    def show_review_popup(self, title, message, transaction_amount, reason, worker_name, is_bartender_tab, selected_bartenders=None):
        """Show review popup"""
        ReviewPopup(self, title, message, transaction_amount, reason, worker_name, is_bartender_tab, selected_bartenders)

    def show_password_popup(self):
        """Show password popup"""
        PasswordPopup(self)

    def show_role_selection_popup(self, worker_name, current_roles=None):
        """Show role selection popup"""
        RoleSelectionPopup(self, worker_name, current_roles)

    def show_worker_selection_popup(self, workers, target_var, title="Select Worker"):
        """Show worker selection popup"""
        WorkerSelectionPopup(self, workers, target_var, title)

    def show_bartender_selection_popup(self, workers, callback):
        """Show bartender selection popup"""
        BartenderSelectionPopup(self, workers, callback)

    # Admin and utility methods
    def check_admin_password(self, password):
        """Check admin password"""
        if password == self.admin_password:
            self.admin_access_granted = True
            self.login_attempts = 0
            # Handle successful login
        else:
            self.login_attempts += 1
            # Handle failed login

    def cancel_admin_login(self):
        """Cancel admin login"""
        self.admin_access_granted = False

    def get_all_possible_roles(self):
        """Get all possible worker roles"""
        return ["Server", "Bartender", "Busser", "Expo", "Runner", "Host", "Manager"]

    def is_worker_new(self, worker_name):
        """Check if worker is new"""
        return worker_name not in self.workers

    def add_worker_with_roles(self, worker_name, roles):
        """Add worker with roles"""
        if self.add_worker(worker_name):
            self.update_worker_roles(worker_name, roles)

    def select_payout_bucket(self, bucket_id):
        """Select bucket for payouts"""
        self.current_payout_bucket = bucket_id
        for bid, btn in self.bucket_buttons.items():
            btn.configure(style="UniformBold.TButton" if bid == bucket_id else "Uniform.TButton")
        self.create_touch_payouts_display()

    def create_touch_payouts_display(self):
        """Create the touch payouts display"""
        for widget in self.payouts_display_frame.winfo_children(): 
            widget.destroy()
        
        bucket = self.current_payout_bucket
        title_frame = ttk.Frame(self.payouts_display_frame)
        title_frame.pack(fill=tk.X, pady=(0, 10))
        bucket_title = bucket.replace('_', ' ').title()
        
        # Get tip amounts from database instead of BUCKETS to avoid multiplication issue
        bartender_info = self.get_payout_info_for_destination(bucket, 'Bartender')
        busser_info = self.get_payout_info_for_destination(bucket, 'Busser')
        expo_info = self.get_payout_info_for_destination(bucket, 'Expo')
        runner_info = self.get_payout_info_for_destination(bucket, 'Runner')
        
        total_tips = (bartender_info['available_amount'] + busser_info['available_amount'] + 
                    expo_info['available_amount'] + runner_info['available_amount'])
        
        ttk.Label(title_frame, text=f"{bucket_title} - Total Tips: ${total_tips:.2f}", style="UniformBold.TLabel").pack()
        if total_tips > 0:
            ttk.Label(title_frame, text=f"Bartender: ${bartender_info['available_amount']:.2f} | Busser: ${busser_info['available_amount']:.2f} | Expo: ${expo_info['available_amount']:.2f} | Runner: ${runner_info['available_amount']:.2f}", style="Uniform.TLabel").pack(pady=(2, 0))

        destinations = self.get_payout_destinations(bucket)
        if not destinations:
            ttk.Label(self.payouts_display_frame, text="No payout destinations for this bucket.", style="UniformBold.TLabel").pack(pady=20)
            return
            
        canvas = tk.Canvas(self.payouts_display_frame)
        scrollbar = ttk.Scrollbar(self.payouts_display_frame, orient="vertical", command=canvas.yview, style="TScrollbar")
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        def frame_width(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind('<Configure>', frame_width)
        
        for i, dest in enumerate(destinations):
            self.create_payout_section_in_frame(scrollable_frame, bucket, dest, i)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def get_payout_destinations(self, bucket):
        """Get payout destinations for a bucket"""
        # Return the standard payout destinations that match database records
        return ['Bartender', 'Busser', 'Expo', 'Runner']

    def create_payout_section_in_frame(self, parent_frame, bucket, destination, index):
        """Create a payout section in the frame"""
        section_frame = ttk.LabelFrame(parent_frame, text=f"{destination} Payout", style="Uniform.TLabelframe")
        section_frame.pack(fill=tk.X, pady=5, padx=5)
        
        # Get payout info
        payout_info = self.get_payout_info_for_destination(bucket, destination)
        
        # Info display
        info_frame = ttk.Frame(section_frame)
        info_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(info_frame, text=f"Available: ${payout_info['available_amount']:.2f}", style="Uniform.TLabel").pack(side=tk.LEFT)
        ttk.Label(info_frame, text=f"Workers: {len(payout_info['assigned_workers'])}", style="Uniform.TLabel").pack(side=tk.LEFT, padx=(20, 0))
        ttk.Label(info_frame, text=f"Per Worker: ${payout_info['per_worker_amount']:.2f}", style="Uniform.TLabel").pack(side=tk.LEFT, padx=(20, 0))
        
        # Workers display
        if payout_info['assigned_workers']:
            workers_text = ", ".join(payout_info['assigned_workers'])
            ttk.Label(section_frame, text=f"Assigned: {workers_text}", style="Uniform.TLabel", wraplength=400).pack(anchor="w", padx=5)
        
        # Buttons
        button_frame = ttk.Frame(section_frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(button_frame, text="Add Worker", command=lambda: self.add_worker_to_payout(bucket, destination), style="Uniform.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Remove Worker", command=lambda: self.remove_worker_from_payout(bucket, destination), style="Uniform.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Clear All", command=lambda: self.clear_payout_workers(bucket, destination), style="Uniform.TButton").pack(side=tk.LEFT, padx=(0, 5))
        
        if payout_info['assigned_workers'] and payout_info['per_worker_amount'] > 0:
            ttk.Button(button_frame, text="Pay Now", command=lambda: self.handle_payout_payment(bucket, destination), style="UniformBold.TButton").pack(side=tk.RIGHT)

    def get_payout_info_for_destination(self, bucket, destination):
        """Get payout information for a destination from database"""
        cursor = self.conn.cursor()
        
        # Calculate available amount from unpaid payouts in database
        cursor.execute(
            '''SELECT SUM(amount) FROM payouts 
               WHERE bucket = ? AND payout_destination = ? AND payout_session_id IS NULL''',
            (bucket, destination)
        )
        result = cursor.fetchone()
        available_amount = result[0] if result and result[0] else 0.0
        
        # Get assigned workers from database
        cursor.execute(
            '''SELECT worker_name FROM worker_assignments 
               WHERE bucket = ? AND payout_destination = ?''',
            (bucket, destination)
        )
        assigned_workers = [row[0] for row in cursor.fetchall()]
        
        per_worker_amount = available_amount / len(assigned_workers) if assigned_workers else 0.0
        
        return {
            'available_amount': available_amount,
            'assigned_workers': assigned_workers,
            'per_worker_amount': per_worker_amount
        }


    def add_worker_to_payout(self, bucket, destination):
        """Add worker to payout"""
        workers_for_role = self.get_workers_by_role(destination)

        if not workers_for_role:
            messagebox.showwarning("No Workers Found", 
                                f"There are no workers assigned the role of '{destination}'.\n\nPlease assign the role to workers in the 'Workers' tab before adding them to this payout.", 
                                parent=self)
            return

        cursor = self.conn.cursor()
        cursor.execute(
            '''SELECT worker_name FROM worker_assignments 
            WHERE bucket = ? AND payout_destination = ?''',
            (bucket, destination)
        )
        already_assigned = [row[0] for row in cursor.fetchall()]

        available_workers = sorted([w for w in workers_for_role if w not in already_assigned])

        if not available_workers:
            messagebox.showinfo("No Available Workers", f"All workers with the '{destination}' role are already assigned to this payout.", parent=self)
            return

        PayoutWorkerSelectionPopup(self, bucket, destination, available_workers, "add")

    def remove_worker_from_payout(self, bucket, destination):
        """Remove worker from payout"""
        # Get assigned workers from database
        cursor = self.conn.cursor()
        cursor.execute(
            '''SELECT worker_name FROM worker_assignments 
               WHERE bucket = ? AND payout_destination = ?''',
            (bucket, destination)
        )
        assigned_workers = [row[0] for row in cursor.fetchall()]
        
        if not assigned_workers:
            messagebox.showinfo("No Workers", "No workers are assigned to remove.")
            return
            
        PayoutWorkerSelectionPopup(self, bucket, destination, assigned_workers, "remove")

    def clear_payout_workers(self, bucket, destination):
        """Clear all workers from payout"""
        if messagebox.askyesno("Clear Workers", f"Remove all workers from {destination}?"):
            cursor = self.conn.cursor()
            cursor.execute(
                '''DELETE FROM worker_assignments 
                   WHERE bucket = ? AND payout_destination = ?''',
                (bucket, destination)
            )
            self.conn.commit()
            self.create_touch_payouts_display()
            messagebox.showinfo("Success", f"All workers removed from {destination}")

    def handle_payout_payment(self, bucket, dest):
        """Handle payout payment"""
        payout_info = self.get_payout_info_for_destination(bucket, dest)
        if not payout_info['assigned_workers'] or payout_info['per_worker_amount'] <= 0:
            messagebox.showwarning("Payment Error", "No workers assigned or no amount to pay out.")
            return
        if not messagebox.askyesno("Confirm Payout", f"This will record a payment for {len(payout_info['assigned_workers'])} worker(s).\n\nAre you sure?"):
            return
        try:
            cursor = self.conn.cursor()
            drawer = self._get_drawer_for_bucket(bucket)
            payout_session_id = f"payout_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

            # 1. Get the submit_id from any payout for this bucket/destination (they should all be the same)
            submit_id = None
            cursor.execute(
                'SELECT DISTINCT submit_id FROM payouts WHERE bucket = ? AND payout_destination = ? AND payout_session_id IS NULL LIMIT 1',
                (bucket, dest)
            )
            submit_id_result = cursor.fetchone()
            if submit_id_result:
                submit_id = submit_id_result[0]

            # 2. Marcar TODOS los payouts pendientes para este pozo como pagados (UNA SOLA VEZ)
            # Se elimina la cláusula LIMIT y se simplifica la consulta.
            cursor.execute(
                '''UPDATE payouts SET payout_session_id = ?
                WHERE bucket = ? AND payout_destination = ? AND payout_session_id IS NULL''',
                (payout_session_id, bucket, dest)
            )

            # 3. Registrar la salida de caja individual para CADA trabajador
            total_paid = 0
            for worker in payout_info['assigned_workers']:
                payout_amount = payout_info['per_worker_amount']

                # Se registra la salida de dinero para cada trabajador individualmente
                cursor.execute(
                    'INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, payout_session_id, submit_id) VALUES (?, ?, ?, ?, ?, ?)',
                    (worker, -payout_amount, f"{dest} payout", drawer, payout_session_id, submit_id)
                )
                total_paid += payout_amount

            self.conn.commit()

            messagebox.showinfo("Payment Successful", f"Successfully recorded a payout of approx. ${total_paid:.2f}.\nThe Cashbox and relevant reports have been updated.")

            self._recalculate_all_data_from_source()
            self.refresh_all_reports()

        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to record payout: {e}", parent=self)

    def _get_drawer_for_bucket(self, bucket):
        """Get cash drawer for bucket"""
        drawer_map = {
            'am_bar': 'AM Bar',
            'westwing': 'West Wing Bar', 
            'sunset': 'Sunset Bar',
            'eastwing': 'Office'
        }
        return drawer_map.get(bucket, 'Office')

    def handle_payout_worker_selections(self, bucket, destination, selected_workers, action):
        """Handle payout worker selections"""
        cursor = self.conn.cursor()
        
        if action == "add":
            added_count = 0
            for worker in selected_workers:
                # Check if worker is already assigned
                cursor.execute(
                    '''SELECT COUNT(*) FROM worker_assignments 
                       WHERE bucket = ? AND payout_destination = ? AND worker_name = ?''',
                    (bucket, destination, worker)
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        '''INSERT INTO worker_assignments (bucket, payout_destination, worker_name) 
                           VALUES (?, ?, ?)''',
                        (bucket, destination, worker)
                    )
                    added_count += 1
            message = f"{added_count} worker(s) added to {destination}."
        else:
            for worker in selected_workers:
                cursor.execute(
                    '''DELETE FROM worker_assignments 
                       WHERE bucket = ? AND payout_destination = ? AND worker_name = ?''',
                    (bucket, destination, worker)
                )
            message = f"{len(selected_workers)} worker(s) removed from {destination}."
        
        self.conn.commit()
        self.create_touch_payouts_display()
        self.refresh_all_reports()
        # No confirmation dialog needed - popup will close automatically

    # Reports tab supporting methods
    def create_report_treeview(self, parent, columns, headings):
        """Create a report treeview widget"""
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings')
        for col, h in zip(columns, headings):
            tree.heading(col, text=h, command=lambda c=col: self.sort_treeview_column(tree, c, False))
            tree.column(col, width=120, anchor='center')
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview, style="TScrollbar")
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return tree

    def sort_treeview_column(self, tree, col, reverse):
        """Sort treeview column"""
        data = [(tree.set(item, col), item) for item in tree.get_children('')]
        def sort_key(val):
            try:
                return float(val.replace('$', '').replace(',', ''))
            except (ValueError, AttributeError):
                return str(val).lower()
        data.sort(key=lambda t: sort_key(t[0]), reverse=reverse)
        for i, (v, item) in enumerate(data):
            tree.move(item, '', i)
        tree.heading(col, command=lambda c=col: self.sort_treeview_column(tree, c, not reverse))

    def populate_report_tab(self):
        """Populate the report tab with data"""
        for tree in [self.tip_in_tree, self.payout_tree]:
            for i in tree.get_children():
                tree.delete(i)
        cursor = self.conn.cursor()
        
        # Populate tip-in history
        cursor.execute('SELECT timestamp, worker_name, bucket, bartips, servertips, expotips, runnertips FROM transactions ORDER BY timestamp DESC')
        for ts, w, b, bt, st, et, rt in cursor.fetchall():
            total = (bt or 0) + (st or 0) + (et or 0) + (rt or 0)
            try:
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            self.tip_in_tree.insert('', 'end', values=(
                dt.strftime('%Y-%m-%d %H:%M'), w, b.replace('_', ' ').title(),
                f"${bt or 0:.2f}", f"${st or 0:.2f}", f"${et or 0:.2f}", f"${rt or 0:.2f}", f"${total:.2f}"
            ))

        # Populate payout history
        cursor.execute('SELECT timestamp, worker_name, bucket, payout_destination, amount FROM payouts ORDER BY timestamp DESC')
        for ts, worker, bucket_name, dest, amount in cursor.fetchall():
            try:
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            formatted_bucket = bucket_name.replace('_', ' ').title()
            formatted_amount = f"${amount:.2f}"
            self.payout_tree.insert('', 'end', values=(
                dt.strftime('%Y-%m-%d %H:%M'), formatted_bucket, dest, worker, formatted_amount
            ))

    def clear_tip_history(self):
        """Clear all tip history"""
        if messagebox.askyesno("Confirm Clear History", "WARNING: This will permanently delete all tip transaction and payout history. This action cannot be undone.", icon='warning'):
            try:
                cursor = self.conn.cursor()
                cursor.execute('DELETE FROM transactions')
                cursor.execute('DELETE FROM payouts')
                self.conn.commit()
                
                self._recalculate_all_data_from_source()
                self.refresh_all_reports()
                self.on_worker_change()
                messagebox.showinfo("Success", "All tip history has been successfully cleared.")
            except Exception as e:
                messagebox.showerror("Error", f"An error occurred while clearing history: {e}")

    # Workers tab supporting methods
    def add_new_worker(self):
        """Add a new worker"""
        worker_name = self.new_worker_name.get().strip()
        if not worker_name:
            messagebox.showwarning("Invalid Name", "Please enter a worker name.")
            return
        
        if self.add_worker(worker_name):
            self.new_worker_name.set("")
            self.refresh_workers_list()
            self.update_worker_stats()
            self.refresh_all_reports()
            messagebox.showinfo("Success", f"Worker '{worker_name}' has been added.")
        else:
            messagebox.showerror("Error", f"Worker '{worker_name}' already exists or could not be added.")

    def refresh_workers_list(self):
        """Refresh the workers list display"""
        for widget in self.workers_scrollable_frame.winfo_children():
            widget.destroy()
        
        self.workers = self.load_workers()
        
        for i, worker in enumerate(self.workers):
            worker_frame = ttk.Frame(self.workers_scrollable_frame)
            worker_frame.pack(fill=tk.X, pady=2)
            
            radio = ttk.Radiobutton(worker_frame, text=worker, variable=self.selected_worker_for_deletion, 
                                   value=worker, command=self.on_worker_selection_change)
            radio.pack(side=tk.LEFT, padx=5)

    def on_worker_selection_change(self):
        """Handle worker selection change in workers tab"""
        selected_worker = self.selected_worker_for_deletion.get()
        if selected_worker:
            self.edit_roles_button.config(state="normal")
            roles = self.get_worker_roles(selected_worker)
            if roles:
                roles_text = f"Roles for {selected_worker}:\n" + "\n".join([f"• {role}" for role in roles])
            else:
                roles_text = f"No roles assigned to {selected_worker}."
            self.worker_roles_var.set(roles_text)
        else:
            self.edit_roles_button.config(state="disabled")
            self.worker_roles_var.set("Select a worker to see their roles.")

    def edit_selected_worker_roles(self):
        """Edit roles for selected worker"""
        selected_worker = self.selected_worker_for_deletion.get()
        if not selected_worker:
            messagebox.showwarning("No Selection", "Please select a worker first.")
            return
        
        current_roles = self.get_worker_roles(selected_worker)
        self.show_role_selection_popup(selected_worker, current_roles)

    def delete_selected_worker(self):
        """Delete selected worker"""
        selected_worker = self.selected_worker_for_deletion.get()
        if not selected_worker:
            messagebox.showwarning("No Selection", "Please select a worker to delete.")
            return
        
        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{selected_worker}'?\n\nThis will also delete all associated tip records and role assignments."):
            try:
                cursor = self.conn.cursor()
                cursor.execute('DELETE FROM workers WHERE name = ?', (selected_worker,))
                cursor.execute('DELETE FROM worker_roles WHERE worker_name = ?', (selected_worker,))
                cursor.execute('DELETE FROM transactions WHERE worker_name = ?', (selected_worker,))
                cursor.execute('DELETE FROM payouts WHERE worker_name = ?', (selected_worker,))
                self.conn.commit()
                
                self.refresh_workers_list()
                self.update_worker_stats()
                self.worker_roles_var.set("Select a worker to see their roles.")
                self.refresh_all_reports()
                messagebox.showinfo("Success", f"Worker '{selected_worker}' has been deleted.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete worker: {e}")

    def update_worker_stats(self):
        """Update worker statistics display"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM workers')
            total_workers = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(DISTINCT worker_name) FROM worker_roles')
            workers_with_roles = cursor.fetchone()[0]
            
            stats_text = f"Total Workers: {total_workers} | Workers with Roles: {workers_with_roles}"
            self.worker_stats_label.config(text=stats_text)
        except Exception as e:
            self.worker_stats_label.config(text="Error loading statistics")

    def get_workers_by_role(self, role):
        """Get workers by role"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT worker_name FROM worker_roles WHERE role = ?', (role,))
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error getting workers by role: {e}")
            return []

    def save_assignments_to_database(self, bucket, assignments):
        """Save worker assignments to database"""
        try:
            cursor = self.conn.cursor()
            # Clear existing assignments for this bucket
            cursor.execute('DELETE FROM worker_assignments WHERE bucket = ?', (bucket,))
            
            # Save new assignments
            for destination, workers in assignments.items():
                for worker in workers:
                    cursor.execute('INSERT INTO worker_assignments (bucket, destination, worker_name) VALUES (?, ?, ?)',
                                 (bucket, destination, worker))
            
            self.conn.commit()
        except Exception as e:
            print(f"Error saving assignments: {e}")

    def update_all_ui_tabs(self):
        """Update all UI tabs"""
        try:
            self.populate_report_tab()
            self.create_touch_payouts_display()
            self.populate_cashbox_tab()
            self.populate_server_report_tab()
            if hasattr(self, 'bartender_tree'):
                self.populate_bartender_report_tab()
            if self.admin_tab_initialized:
                self.populate_admin_tab()
        except Exception as e:
            print(f"Error updating UI tabs: {e}")

    def refresh_all_reports(self):
        """Refresh all report tabs automatically"""
        try:
            # Refresh all report tabs
            self.populate_server_report_tab()
            self.populate_bartender_report_tab()
            self.populate_report_tab()
            self.populate_cashbox_tab()
            
            # Also refresh payouts display
            self.create_touch_payouts_display()
            
        except Exception as e:
            print(f"Error refreshing reports: {e}")

    # Server Report tab supporting methods
    def populate_server_report_tab(self):
        """Populate the server report tab with data"""
        if not hasattr(self, 'server_report_tree'):
            return
        for i in self.server_report_tree.get_children():
            self.server_report_tree.delete(i)
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, date, server, bucket, cash_tips, non_cash_tips, gratuity, sum_tips_for_payout, net_sales, tipped_perc_of_net_sales FROM servers ORDER BY timestamp DESC')
        for row in cursor.fetchall():
            db_id, date, server, bucket, cash, non_cash, grat, payout, sales, perc = row
            self.server_report_tree.insert('', 'end', iid=db_id, values=(
                date, server, bucket.replace('_', ' ').title(), f"${cash:.2f}", f"${non_cash:.2f}", 
                f"${grat:.2f}", f"${payout:.2f}", f"${sales:.2f}", perc))

    def populate_bartender_report_tab(self):
        """Populate the bartender report tab with data"""
        if not hasattr(self, 'bartender_tree'):
            return
        for i in self.bartender_tree.get_children():
            self.bartender_tree.delete(i)
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, date, bartender, job_title, cash_tips, credit_tips, sum_tips_for_payout, net_sales, tipped_perc_of_net_sales, bar_name FROM bartenders ORDER BY timestamp DESC')
        for row in cursor.fetchall():
            db_id, date, bartender, job, cash, credit, payout, sales, perc, bar = row
            self.bartender_tree.insert('', 'end', iid=db_id, values=(
                date, bartender, job, bar, f"${cash:.2f}", f"${credit:.2f}", f"${payout:.2f}", f"${sales:.2f}", perc))

    # Cashbox tab supporting methods
    def select_cash_drawer(self, drawer_name):
        """Select cash drawer for cashbox"""
        self.selected_cash_drawer.set(drawer_name)
        for name, btn in self.cashbox_buttons.items():
            btn.configure(style="UniformBold.TButton" if name == drawer_name else "Uniform.TButton")
        self.populate_cashbox_tab()

    def on_cashbox_entry_select(self, event=None):
        """Handle cashbox entry selection"""
        if hasattr(self, 'cashbox_tree') and hasattr(self, 'delete_cashbox_button'):
            if self.cashbox_tree.selection():
                self.delete_cashbox_button.config(state="normal")
            else:
                self.delete_cashbox_button.config(state="disabled")

    def delete_cashbox_entry_and_linked_records(self):
        """Delete cashbox entry and linked records"""
        selected_iid = self.cashbox_tree.focus()
        if not selected_iid:
            messagebox.showwarning("No Selection", "Please select an entry to delete.", parent=self)
            return

        msg = "Are you sure you want to delete this entry?\n\nThis will also delete any linked bartender, server, or payout records. This action cannot be undone."
        if not messagebox.askyesno("Confirm Delete", msg, icon='warning', parent=self):
            return

        try:
            cursor = self.conn.cursor()
            
            cursor.execute("SELECT submit_id, payout_session_id FROM cashbox_ledger WHERE id = ?", (selected_iid,))
            result = cursor.fetchone()
            submit_id_to_delete, payout_session_id_to_delete = (result[0], result[1]) if result else (None, None)

            if submit_id_to_delete:
                cursor.execute("DELETE FROM bartenders WHERE submit_id = ?", (submit_id_to_delete,))
                cursor.execute("DELETE FROM servers WHERE submit_id = ?", (submit_id_to_delete,))
            
            if payout_session_id_to_delete:
                cursor.execute("DELETE FROM payouts WHERE payout_session_id = ?", (payout_session_id_to_delete,))
                cursor.execute("DELETE FROM cashbox_ledger WHERE payout_session_id = ?", (payout_session_id_to_delete,))
            else:
                cursor.execute("DELETE FROM cashbox_ledger WHERE id = ?", (selected_iid,))

            self.conn.commit()
            messagebox.showinfo("Success", "The selected entry and all linked records have been deleted.", parent=self)

            self._recalculate_all_data_from_source()
            self.refresh_all_reports()

        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to delete entry: {e}", parent=self)

    # Server and Bartender record deletion methods
    def on_server_record_select(self, event=None):
        """Handle server record selection"""
        if hasattr(self, 'server_report_tree') and hasattr(self, 'delete_server_button'):
            if self.server_report_tree.selection():
                self.delete_server_button.config(state="normal")
            else:
                self.delete_server_button.config(state="disabled")

    def on_bartender_record_select(self, event=None):
        """Handle bartender record selection"""
        if hasattr(self, 'bartender_tree') and hasattr(self, 'delete_bartender_button'):
            if self.bartender_tree.selection():
                self.delete_bartender_button.config(state="normal")
            else:
                self.delete_bartender_button.config(state="disabled")

    def delete_selected_server_record(self):
        """Delete selected server record and related payouts/cashbox entries"""
        selected_iid = self.server_report_tree.focus()
        if not selected_iid:
            messagebox.showwarning("No Selection", "Please select a server record to delete.", parent=self)
            return

        msg = "Are you sure you want to delete this server record?\n\nThis will also delete any related payout records and cashbox entries. This action cannot be undone."
        if not messagebox.askyesno("Confirm Delete", msg, icon='warning', parent=self):
            return

        try:
            cursor = self.conn.cursor()
            
            # Get submit_id for the server record
            cursor.execute("SELECT submit_id FROM servers WHERE id = ?", (selected_iid,))
            result = cursor.fetchone()
            submit_id = result[0] if result else None

            # Delete server record
            cursor.execute("DELETE FROM servers WHERE id = ?", (selected_iid,))
            
            # Delete related payouts and cashbox entries if submit_id exists
            if submit_id:
                cursor.execute("DELETE FROM payouts WHERE submit_id = ?", (submit_id,))
                cursor.execute("DELETE FROM cashbox_ledger WHERE submit_id = ?", (submit_id,))

            self.conn.commit()
            messagebox.showinfo("Success", "The server record and all related entries have been deleted.", parent=self)

            self._recalculate_all_data_from_source()
            self.refresh_all_reports()

        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to delete server record: {e}", parent=self)

    def delete_selected_bartender_record(self):
        """Delete selected bartender record and all related records with same submit_id"""
        selected_iid = self.bartender_tree.focus()
        if not selected_iid:
            messagebox.showwarning("No Selection", "Please select a bartender record to delete.", parent=self)
            return

        try:
            cursor = self.conn.cursor()
            
            # Get submit_id for the selected bartender record
            cursor.execute("SELECT submit_id FROM bartenders WHERE id = ?", (selected_iid,))
            result = cursor.fetchone()
            submit_id = result[0] if result else None

            if not submit_id:
                messagebox.showwarning("No Submit ID", "Cannot delete record: no submit_id found.", parent=self)
                return

            # Check how many bartender records share this submit_id
            cursor.execute("SELECT COUNT(*), GROUP_CONCAT(bartender) FROM bartenders WHERE submit_id = ?", (submit_id,))
            count_result = cursor.fetchone()
            record_count = count_result[0] if count_result else 0
            bartender_names = count_result[1] if count_result else ""

            if record_count > 1:
                msg = f"This will delete ALL {record_count} bartender records that were submitted together:\n\n{bartender_names}\n\nThis will also delete all related payout records and cashbox entries. This action cannot be undone."
            else:
                msg = "Are you sure you want to delete this bartender record?\n\nThis will also delete any related payout records and cashbox entries. This action cannot be undone."
            
            if not messagebox.askyesno("Confirm Delete", msg, icon='warning', parent=self):
                return

            # Delete ALL bartender records with the same submit_id
            cursor.execute("DELETE FROM bartenders WHERE submit_id = ?", (submit_id,))
            
            # Delete related payouts and cashbox entries
            cursor.execute("DELETE FROM payouts WHERE submit_id = ?", (submit_id,))
            cursor.execute("DELETE FROM cashbox_ledger WHERE submit_id = ?", (submit_id,))

            self.conn.commit()
            
            if record_count > 1:
                messagebox.showinfo("Success", f"All {record_count} bartender records and related entries have been deleted.", parent=self)
            else:
                messagebox.showinfo("Success", "The bartender record and all related entries have been deleted.", parent=self)

            self._recalculate_all_data_from_source()
            self.update_all_ui_tabs()

        except Exception as e:
            self.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to delete bartender record: {e}", parent=self)

    def __del__(self):
        """Cleanup when app is destroyed"""
        if hasattr(self, 'db_manager'):
            self.db_manager.close()
