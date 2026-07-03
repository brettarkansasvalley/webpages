#!/usr/bin/env python3
"""
UI Popup classes for the Restaurant Tip Distribution System
"""
#ui_popups.py
import tkinter as tk
from tkinter import ttk, messagebox
import json
from datetime import datetime
from config import UNIFORM_FONT, UNIFORM_BOLD, TREEVIEW_HEADING_FONT, SCROLLBAR_WIDTH


class NumericKeyboardPopup(tk.Toplevel):
    def __init__(self, master, target_var):
        super().__init__(master)
        self.title("Numeric Keypad")
        self.result = ""
        self.target_var = target_var

        w, h = 280, 420
        x = master.winfo_rootx() + max(master.winfo_width()//2 - w//2, 10)
        y = master.winfo_rooty() + 80
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.transient(master)

        self.display_var = tk.StringVar()
        display = tk.Entry(self, textvariable=self.display_var, font=("Helvetica", 18, "bold"),
                           justify="right", relief="solid", bd=2)
        display.grid(row=0, column=0, columnspan=3, padx=10, pady=(10, 15), ipady=8, sticky="nsew")

        keys = [
            ['7', '8', '9'],
            ['4', '5', '6'],
            ['1', '2', '3'],
            ['0', '.', '⌫']
        ]

        for r, rowk in enumerate(keys):
            for c, key in enumerate(rowk):
                btn = tk.Button(self, text=key, font=UNIFORM_BOLD, command=lambda val=key: self._on_value(val))
                btn.grid(row=r+1, column=c, sticky="nsew", padx=4, pady=4, ipady=4)

        ok_btn = tk.Button(self, text='OK', font=UNIFORM_BOLD, command=lambda:self._on_value('OK'))
        ok_btn.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=4, pady=4, ipady=4)

        for i in range(1, 6): self.grid_rowconfigure(i, weight=1)
        for i in range(3): self.grid_columnconfigure(i, weight=1)
        self.after(50, self.grab_set)

    def _on_value(self, val):
        if val == 'OK':
            try:
                self.target_var.set(float(self.display_var.get() or "0"))
            except ValueError:
                self.target_var.set(0.0)
            self.destroy()
        elif val == '⌫':
            current = self.display_var.get()
            self.display_var.set(current[:-1])
        else:
            current = self.display_var.get()
            if val == '.' and '.' in current:
                return
            self.display_var.set(current + val)


class AlphaKeyboardPopup(tk.Toplevel):
    def __init__(self, master, target_var, label="Enter Name"):
        super().__init__(master)
        self.title(label)
        self.result = target_var.get()
        self.target_var = target_var

        master.update_idletasks()

        w, h = 500, 280
        x = master.winfo_rootx() + (master.winfo_width() // 2) - (w // 2)
        y = master.winfo_rooty() + (master.winfo_height() // 2) - (h // 2)
        
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.transient(master)

        self.display_var = tk.StringVar(value=self.result)
        display = tk.Entry(self, textvariable=self.display_var, font=("Helvetica", 16, "bold"), relief="solid", bd=2)
        display.pack(fill=tk.X, padx=10, pady=(10, 10), ipady=6)

        letters = [
            list("QWERTYUIOP"),
            list("ASDFGHJKL"),
            list("ZXCVBNM")
        ]

        for r, row in enumerate(letters):
            row_frame = tk.Frame(self)
            row_frame.pack(pady=2)
            for ch in row:
                btn = tk.Button(row_frame, text=ch, font=UNIFORM_FONT,
                                command=lambda val=ch: self._on_char(val), width=3, height=1)
                btn.pack(side=tk.LEFT, padx=2, pady=2)

        bottom_frame = tk.Frame(self)
        bottom_frame.pack(pady=5)
        
        space = tk.Button(bottom_frame, text="Space", font=UNIFORM_FONT, command=lambda:self._on_char(' '), width=15)
        space.pack(side=tk.LEFT, padx=5)
        
        back = tk.Button(bottom_frame, text="Backspace", font=UNIFORM_FONT, command=self._on_back, width=10)
        back.pack(side=tk.LEFT, padx=5)
        
        ok = tk.Button(bottom_frame, text="OK", font=UNIFORM_BOLD, command=self._on_ok, width=6)
        ok.pack(side=tk.LEFT, padx=5)
        
        self.grab_set()

    def _on_char(self, c):
        current = self.display_var.get()
        self.display_var.set(current + c)

    def _on_back(self):
        current = self.display_var.get()
        self.display_var.set(current[:-1])

    def _on_ok(self):
        self.target_var.set(self.display_var.get())
        self.destroy()


class ReviewPopup(tk.Toplevel):
    def __init__(self, master, title, message, transaction_amount, reason, worker_name, is_bartender_tab, selected_bartenders=None, has_report_data=False):
        super().__init__(master)
        self.master_app = master
        self.title(title)
        self.transaction_amount = transaction_amount
        self.reason = reason
        self.worker_name = worker_name
        self.is_bartender_tab = is_bartender_tab
        self.selected_bartenders = selected_bartenders if selected_bartenders else []

        w, h = 420, 320
        x = self.master_app.winfo_rootx() + max(self.master_app.winfo_width()//2 - w//2, 10)
        y = self.master_app.winfo_rooty() + 150
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        message_label = ttk.Label(self, text=message, style="Uniform.TLabel", justify=tk.LEFT, wraplength=w-20)
        message_label.pack(pady=20, padx=10, expand=True, fill=tk.BOTH)

        button_frame = ttk.Frame(self)
        button_frame.pack(pady=10, fill=tk.X, side=tk.BOTTOM, padx=10)
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)

        if self.transaction_amount != 0 or self.is_bartender_tab or (not self.is_bartender_tab and has_report_data):
            pay_button = ttk.Button(button_frame, text="Pay Now" if self.transaction_amount != 0 else "Save Report", command=self.handle_pay_now, style="UniformBold.TButton")
            pay_button.grid(row=0, column=0, padx=10, sticky="ew", ipady=8)

        pay_button_is_visible = self.transaction_amount != 0 or self.is_bartender_tab or (not self.is_bartender_tab and has_report_data)

        close_button = ttk.Button(button_frame, text="Close", command=self.destroy, style="Uniform.TButton")
        close_button.grid(
            row=0,
            column=1 if pay_button_is_visible else 0,
            columnspan=1 if pay_button_is_visible else 2,
            padx=10, sticky="ew", ipady=8
        )

    def handle_pay_now(self):
        try:
            cursor = self.master_app.conn.cursor()
            
            submit_id = f"sub_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

            if self.is_bartender_tab:
                num_bartenders = len(self.selected_bartenders)
                if num_bartenders == 0: return

                cash_tips_total = self.master_app.bt_cashtips_var.get()
                credit_tips_total = self.master_app.bt_creditcardtip_var.get()
                net_sales_total = self.master_app.bt_netsales_var.get()
                payout_tips_total = (self.master_app.bt_servertips_var.get() +
                                     self.master_app.bt_expotips_var.get() +
                                     self.master_app.bt_runnertips_var.get())
                gross_tip_perc_str = self.master_app.bt_gross_tip_percentage_var.get().replace("Gross Tip %: ", "")
                date_str = datetime.now().strftime('%m/%d/%Y')
                current_bucket = self.master_app.bt_selected_bucket.get()
                bar_name = self.master_app._get_drawer_for_bucket(current_bucket)

                cash_tips_per = cash_tips_total / num_bartenders
                credit_tips_per = credit_tips_total / num_bartenders
                net_sales_per = net_sales_total / num_bartenders
                payout_tips_per = payout_tips_total / num_bartenders

                for bartender_name in self.selected_bartenders:
                    cursor.execute(
                        '''INSERT INTO bartenders
                           (date, cash_tips, credit_tips, sum_tips_for_payout, net_sales,
                            tipped_perc_of_net_sales, job_title, bartender, bar_name, submit_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (date_str, cash_tips_per, credit_tips_per, payout_tips_per, net_sales_per,
                         gross_tip_perc_str, "Bartender", bartender_name, bar_name, submit_id)
                    )
                    
                    # Create corresponding payout records for each payout type
                    if self.master_app.bt_servertips_var.get() > 0:
                        cursor.execute(
                            '''INSERT INTO payouts (worker_name, amount, bucket, payout_destination, submit_id)
                            VALUES (?, ?, ?, ?, ?)''',
                            (bartender_name, self.master_app.bt_servertips_var.get() / num_bartenders, current_bucket, "Busser", submit_id)
                        )
                    if self.master_app.bt_expotips_var.get() > 0:
                        cursor.execute(
                            '''INSERT INTO payouts (worker_name, amount, bucket, payout_destination, submit_id)
                               VALUES (?, ?, ?, ?, ?)''',
                            (bartender_name, self.master_app.bt_expotips_var.get() / num_bartenders, current_bucket, "Expo", submit_id)
                        )
                    if self.master_app.bt_runnertips_var.get() > 0:
                        cursor.execute(
                            '''INSERT INTO payouts (worker_name, amount, bucket, payout_destination, submit_id)
                               VALUES (?, ?, ?, ?, ?)''',
                            (bartender_name, self.master_app.bt_runnertips_var.get() / num_bartenders, current_bucket, "Runner", submit_id)
                        )
                
                # New cashbox_ledger entries as per user requirements
                
                # 1. Sum of 'Add tips for Payout' goes to 'Office' cash drawer
                total_payout_tips = (self.master_app.bt_servertips_var.get() + 
                                   self.master_app.bt_expotips_var.get() + 
                                   self.master_app.bt_runnertips_var.get())
                if total_payout_tips > 0:
                    cursor.execute(
                        'INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, submit_id) VALUES (?, ?, ?, ?, ?)',
                        ("BAR GROUP", total_payout_tips, "Bartender payout tips", "Office", submit_id)
                    )
                
                # 2. Use the pre-calculated transaction_amount for the settlement.
                if self.transaction_amount != 0:
                    drawer = self.master_app._get_drawer_for_bucket(current_bucket)
                    cursor.execute(
                        'INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, submit_id) VALUES (?, ?, ?, ?, ?)',
                        ("BAR GROUP", self.transaction_amount, self.reason, drawer, submit_id)
                    )

                messagebox.showinfo("Success", f"{num_bartenders} records inserted into the Bartender ledger.", parent=self)
                self.master_app.populate_bartender_tab()
                self.master_app.bt_clear_current_tip_input(confirm=False)
 
            else: # Regular server settlement
                payout_tips = (self.master_app.bartips_var.get() + self.master_app.servertips_var.get() +
                               self.master_app.expotips_var.get() + self.master_app.runnertips_var.get())
                
                cursor.execute(
                    '''INSERT INTO servers
                       (date, server, job_title, bucket, cash_tips, non_cash_tips, gratuity, 
                        sum_tips_for_payout, net_sales, tipped_perc_of_net_sales, submit_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        datetime.now().strftime('%m/%d/%Y'),
                        self.worker_name,
                        "Server",
                        self.master_app.selected_bucket.get(),
                        self.master_app.cashtips_var.get(),
                        self.master_app.creditcardtip_var.get(),
                        self.master_app.gratuity_var.get(),
                        payout_tips,
                        self.master_app.netsales_var.get(),
                        self.master_app.gross_tip_percentage_var.get().replace("Gross Tip %: ", ""),
                        submit_id
                    )
                )
                
                # Create corresponding payout records for each payout type
                current_bucket = self.master_app.selected_bucket.get()

                if self.master_app.bartips_var.get() > 0:
                    cursor.execute(
                        '''INSERT INTO payouts (worker_name, amount, bucket, payout_destination, submit_id)
                           VALUES (?, ?, ?, ?, ?)''',
                        (self.worker_name, self.master_app.bartips_var.get(), current_bucket, "Bartender", submit_id)
                    )
                if self.master_app.servertips_var.get() > 0:
                    cursor.execute(
                        '''INSERT INTO payouts (worker_name, amount, bucket, payout_destination, submit_id)
                           VALUES (?, ?, ?, ?, ?)''',
                        (self.worker_name, self.master_app.servertips_var.get(), current_bucket, "Busser", submit_id)
                    )
                if self.master_app.expotips_var.get() > 0:
                    cursor.execute(
                        '''INSERT INTO payouts (worker_name, amount, bucket, payout_destination, submit_id)
                           VALUES (?, ?, ?, ?, ?)''',
                        (self.worker_name, self.master_app.expotips_var.get(), current_bucket, "Expo", submit_id)
                    )
                if self.master_app.runnertips_var.get() > 0:
                    cursor.execute(
                        '''INSERT INTO payouts (worker_name, amount, bucket, payout_destination, submit_id)
                           VALUES (?, ?, ?, ?, ?)''',
                        (self.worker_name, self.master_app.runnertips_var.get(), current_bucket, "Runner", submit_id)
                    )

                if self.transaction_amount != 0:
                    drawer = self.master_app._get_drawer_for_bucket(self.master_app.selected_bucket.get())
                    cursor.execute(
                        'INSERT INTO cashbox_ledger (worker_name, amount, reason, cash_drawer, submit_id) VALUES (?, ?, ?, ?, ?)',
                        (self.worker_name, self.transaction_amount, self.reason, drawer, submit_id)
                    )
                
                self.master_app.populate_server_report_tab()

            self.master_app.populate_cashbox_tab()
            if self.master_app.admin_tab_initialized:
                self.master_app.populate_admin_tab()

            self.master_app.conn.commit()

            if self.is_bartender_tab:
                self.master_app.bt_cash_in_drawer_var.set(0.0)
            else:
                self.master_app.clear_current_tip_input(confirm=False)
                self.master_app.owed_to_server_var.set(0.0)
                self.master_app.owed_to_restaurant_var.set(0.0)

            self.destroy()

        except Exception as e:
            self.master_app.conn.rollback()
            messagebox.showerror("Database Error", f"Failed to record transaction: {e}", parent=self)


class PasswordPopup(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master_app = master
        self.title("Admin Access")
        self.entered_password = ""

        w, h = 280, 450
        x = master.winfo_rootx() + max(master.winfo_width()//2 - w//2, 10)
        y = master.winfo_rooty() + 80
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.transient(master)

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.display_var = tk.StringVar()

        self.message_label = tk.Label(self, text="Enter Admin PIN", font=UNIFORM_BOLD)
        self.message_label.grid(row=0, column=0, columnspan=3, pady=(10, 0))

        display = tk.Entry(self, textvariable=self.display_var, font=("Helvetica", 18, "bold"),
                           justify="center", relief="solid", bd=2, show="*")
        display.grid(row=1, column=0, columnspan=3, padx=10, pady=(5, 15), ipady=8, sticky="nsew")

        keys = [['7', '8', '9'], ['4', '5', '6'], ['1', '2', '3'], ['C', '0', '⌫']]

        for r, rowk in enumerate(keys):
            for c, key in enumerate(rowk):
                btn = tk.Button(self, text=key, font=UNIFORM_BOLD, command=lambda val=key: self._on_value(val))
                btn.grid(row=r+2, column=c, sticky="nsew", padx=4, pady=4)

        enter_btn = tk.Button(self, text="Enter", font=UNIFORM_BOLD, command=self.on_enter)
        enter_btn.grid(row=6, column=0, columnspan=3, sticky="nsew", padx=4, pady=4)

        for i in range(2, 7): self.grid_rowconfigure(i, weight=1)
        for i in range(3): self.grid_columnconfigure(i, weight=1)

        self.after(50, self.grab_set)

    def _on_value(self, val):
        if val == '⌫': self.display_var.set(self.display_var.get()[:-1])
        elif val == 'C': self.display_var.set("")
        else: self.display_var.set(self.display_var.get() + val)

    def on_enter(self):
        self.entered_password = self.display_var.get()
        self.master_app.check_admin_password(self.entered_password)

    def on_cancel(self):
        self.master_app.cancel_admin_login()
        self.destroy()

    def show_error(self, message):
        self.message_label.config(text=message, fg="red")
        self.display_var.set("")


class RoleSelectionPopup(tk.Toplevel):
    def __init__(self, master, worker_name, current_roles=None):
        super().__init__(master)
        self.master_app = master
        self.worker_name = worker_name
        self.title(f"Assign Roles to {worker_name}")
        
        w, h = 450, 550
        x = self.master_app.winfo_rootx() + max(self.master_app.winfo_width()//2 - w//2, 10)
        y = self.master_app.winfo_rooty() + 50
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        
        ttk.Label(self, text="Select Worker Roles:", style="UniformBold.TLabel").pack(pady=(10, 5))

        # --- SECCIÓN MODIFICADA PARA EL NUEVO SCROLLBAR ---
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, font=TREEVIEW_HEADING_FONT, selectmode='multiple', exportselection=False, highlightthickness=0)
        self.listbox.grid(row=0, column=0, sticky="nsew")

        controls_frame = ttk.Frame(list_frame, width=SCROLLBAR_WIDTH)
        controls_frame.grid(row=0, column=1, sticky='ns', padx=(5, 0))
        controls_frame.grid_propagate(False)
        
        controls_frame.grid_rowconfigure(1, weight=1)
        controls_frame.grid_columnconfigure(0, weight=1)

        up_button = ttk.Button(controls_frame, text="▲", style="Scroll.TButton")
        scrollbar = ttk.Scrollbar(controls_frame, orient="vertical", style="Arrowless.TScrollbar")
        down_button = ttk.Button(controls_frame, text="▼", style="Scroll.TButton")

        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.configure(command=self.listbox.yview)
        up_button.bind('<ButtonPress-1>', lambda event, w=self.listbox, d=-1: self.master.start_scroll(w, d))
        up_button.bind('<ButtonRelease-1>', self.master.stop_scroll)
        down_button.bind('<ButtonPress-1>', lambda event, w=self.listbox, d=1: self.master.start_scroll(w, d))
        down_button.bind('<ButtonRelease-1>', self.master.stop_scroll)

        up_button.grid(row=0, column=0, sticky='ew')
        scrollbar.grid(row=1, column=0, sticky='ns')
        down_button.grid(row=2, column=0, sticky='ew')

        self.all_roles = self.master_app.get_all_possible_roles()
        for i, role in enumerate(self.all_roles):
            self.listbox.insert(tk.END, role)
            if current_roles and role in current_roles:
                self.listbox.selection_set(i)
        
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)
        button_frame.columnconfigure((0, 1), weight=1)
        
        ttk.Button(button_frame, text="Save Roles", command=self._on_ok, style="UniformBold.TButton").grid(row=0, column=0, sticky=tk.EW, padx=(0,5), ipady=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy, style="Uniform.TButton").grid(row=0, column=1, sticky=tk.EW, padx=(5,0), ipady=5)

    def _on_ok(self):
        selected_indices = self.listbox.curselection()
        selected_roles = [self.all_roles[i] for i in selected_indices]
        
        if self.master_app.is_worker_new(self.worker_name):
            self.master_app.add_worker_with_roles(self.worker_name, selected_roles)
        else:
            self.master_app.update_worker_roles(self.worker_name, selected_roles)
        self.destroy()


class PayoutWorkerSelectionPopup(tk.Toplevel):
    def __init__(self, master, bucket, destination, available_workers, action):
        super().__init__(master)
        self.master_app = master
        self.bucket = bucket
        self.destination = destination
        self.action = action
        self.title(f"{action.title()} Workers for {destination}")

        w, h = 450, 550
        x = self.master_app.winfo_rootx() + max(self.master_app.winfo_width()//2 - w//2, 10)
        y = self.master_app.winfo_rooty() + 50
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        label_text = f"Select workers to {self.action}:"
        ttk.Label(self, text=label_text, style="UniformBold.TLabel").pack(pady=(10, 5))
        
        # --- SECCIÓN MODIFICADA PARA EL NUEVO SCROLLBAR ---
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, font=TREEVIEW_HEADING_FONT, selectmode='multiple', exportselection=False, highlightthickness=0)
        self.listbox.grid(row=0, column=0, sticky="nsew")

        controls_frame = ttk.Frame(list_frame, width=SCROLLBAR_WIDTH)
        controls_frame.grid(row=0, column=1, sticky='ns', padx=(5, 0))
        controls_frame.grid_propagate(False)
        
        controls_frame.grid_rowconfigure(1, weight=1)
        controls_frame.grid_columnconfigure(0, weight=1)

        up_button = ttk.Button(controls_frame, text="▲", style="Scroll.TButton")
        scrollbar = ttk.Scrollbar(controls_frame, orient="vertical", style="Arrowless.TScrollbar")
        down_button = ttk.Button(controls_frame, text="▼", style="Scroll.TButton")

        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.configure(command=self.listbox.yview)
        up_button.bind('<ButtonPress-1>', lambda event, w=self.listbox, d=-1: self.master.start_scroll(w, d))
        up_button.bind('<ButtonRelease-1>', self.master.stop_scroll)
        down_button.bind('<ButtonPress-1>', lambda event, w=self.listbox, d=1: self.master.start_scroll(w, d))
        down_button.bind('<ButtonRelease-1>', self.master.stop_scroll)

        up_button.grid(row=0, column=0, sticky='ew')
        scrollbar.grid(row=1, column=0, sticky='ns')
        down_button.grid(row=2, column=0, sticky='ew')

        self.worker_list = sorted(available_workers)
        for worker in self.worker_list:
            self.listbox.insert(tk.END, worker)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)
        button_frame.columnconfigure((0, 1), weight=1)

        ok_text = "Add Selected" if action == 'add' else "Remove Selected"
        ttk.Button(button_frame, text=ok_text, command=self._on_ok, style="UniformBold.TButton").grid(row=0, column=0, sticky=tk.EW, padx=(0,5), ipady=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy, style="Uniform.TButton").grid(row=0, column=1, sticky=tk.EW, padx=(5,0), ipady=5)

    def _on_ok(self):
        selected_indices = self.listbox.curselection()
        selected_workers = [self.worker_list[i] for i in selected_indices]
        
        if not selected_workers:
            messagebox.showwarning("No Selection", "Please select at least one worker.", parent=self)
            return

        self.master_app.handle_payout_worker_selections(self.bucket, self.destination, selected_workers, self.action)
        self.destroy()


class WorkerSelectionPopup(tk.Toplevel):
    def __init__(self, master, workers, target_var, title="Select Worker"):
        super().__init__(master)
        self.master_app = master
        self.workers = workers
        self.target_var = target_var
        self.title(title)

        w, h = 450, 550
        x = self.master_app.winfo_rootx() + max(self.master_app.winfo_width()//2 - w//2, 10)
        y = self.master_app.winfo_rooty() + 50
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ttk.Label(self, text=title + ":", style="UniformBold.TLabel").pack(pady=(10, 5))
        
        # --- SECCIÓN MODIFICADA PARA EL NUEVO SCROLLBAR ---
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, font=TREEVIEW_HEADING_FONT, selectmode='single', exportselection=False, highlightthickness=0)
        self.listbox.grid(row=0, column=0, sticky="nsew")

        controls_frame = ttk.Frame(list_frame, width=SCROLLBAR_WIDTH)
        controls_frame.grid(row=0, column=1, sticky='ns', padx=(5, 0))
        controls_frame.grid_propagate(False)
        
        controls_frame.grid_rowconfigure(1, weight=1)
        controls_frame.grid_columnconfigure(0, weight=1)

        up_button = ttk.Button(controls_frame, text="▲", style="Scroll.TButton")
        scrollbar = ttk.Scrollbar(controls_frame, orient="vertical", style="Arrowless.TScrollbar")
        down_button = ttk.Button(controls_frame, text="▼", style="Scroll.TButton")

        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.configure(command=self.listbox.yview)
        up_button.bind('<ButtonPress-1>', lambda event, w=self.listbox, d=-1: self.master.start_scroll(w, d))
        up_button.bind('<ButtonRelease-1>', self.master.stop_scroll)
        down_button.bind('<ButtonPress-1>', lambda event, w=self.listbox, d=1: self.master.start_scroll(w, d))
        down_button.bind('<ButtonRelease-1>', self.master.stop_scroll)

        up_button.grid(row=0, column=0, sticky='ew')
        scrollbar.grid(row=1, column=0, sticky='ns')
        down_button.grid(row=2, column=0, sticky='ew')

        for worker in self.workers:
            self.listbox.insert(tk.END, worker)

        self.listbox.bind("<Double-1>", self._on_ok)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)
        button_frame.columnconfigure((0, 1), weight=1)

        ttk.Button(button_frame, text="OK", command=self._on_ok, style="UniformBold.TButton").grid(row=0, column=0, sticky=tk.EW, padx=(0,5), ipady=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy, style="Uniform.TButton").grid(row=0, column=1, sticky=tk.EW, padx=(5,0), ipady=5)

    def _on_ok(self, event=None):
        selected_indices = self.listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("No Selection", "Please select a worker.", parent=self)
            return
        
        selected_worker = self.workers[selected_indices[0]]
        self.target_var.set(selected_worker)
        self.destroy()


class BartenderSelectionPopup(tk.Toplevel):
    def __init__(self, master, workers, callback):
        super().__init__(master)
        self.master_app = master
        self.workers = workers
        self.callback = callback
        self.title("Select Bartenders")

        w, h = 450, 550
        x = self.master_app.winfo_rootx() + max(self.master_app.winfo_width()//2 - w//2, 10)
        y = self.master_app.winfo_rooty() + 50
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ttk.Label(self, text="Select 1 to 3 Bartenders:", style="UniformBold.TLabel").pack(pady=(10, 5))
        
        # --- SECCIÓN MODIFICADA PARA EL NUEVO SCROLLBAR ---
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(list_frame, font=TREEVIEW_HEADING_FONT, selectmode='multiple', exportselection=False, highlightthickness=0)
        self.listbox.grid(row=0, column=0, sticky="nsew")

        controls_frame = ttk.Frame(list_frame, width=SCROLLBAR_WIDTH)
        controls_frame.grid(row=0, column=1, sticky='ns', padx=(5, 0))
        controls_frame.grid_propagate(False)
        
        controls_frame.grid_rowconfigure(1, weight=1)
        controls_frame.grid_columnconfigure(0, weight=1)

        up_button = ttk.Button(controls_frame, text="▲", style="Scroll.TButton")
        scrollbar = ttk.Scrollbar(controls_frame, orient="vertical", style="Arrowless.TScrollbar")
        down_button = ttk.Button(controls_frame, text="▼", style="Scroll.TButton")

        self.listbox.configure(yscrollcommand=scrollbar.set)
        scrollbar.configure(command=self.listbox.yview)
        up_button.bind('<ButtonPress-1>', lambda event, w=self.listbox, d=-1: self.master.start_scroll(w, d))
        up_button.bind('<ButtonRelease-1>', self.master.stop_scroll)
        down_button.bind('<ButtonPress-1>', lambda event, w=self.listbox, d=1: self.master.start_scroll(w, d))
        down_button.bind('<ButtonRelease-1>', self.master.stop_scroll)

        up_button.grid(row=0, column=0, sticky='ew')
        scrollbar.grid(row=1, column=0, sticky='ns')
        down_button.grid(row=2, column=0, sticky='ew')

        for worker in self.workers:
            self.listbox.insert(tk.END, worker)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)
        button_frame.columnconfigure((0, 1), weight=1)

        ttk.Button(button_frame, text="OK", command=self._on_ok, style="UniformBold.TButton").grid(row=0, column=0, sticky=tk.EW, padx=(0,5), ipady=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy, style="Uniform.TButton").grid(row=0, column=1, sticky=tk.EW, padx=(5,0), ipady=5)

    def _on_ok(self):
        selected_indices = self.listbox.curselection()
        selected_workers = [self.workers[i] for i in selected_indices]
        
        if not 1 <= len(selected_workers) <= 3:
            messagebox.showwarning("Invalid Selection", "Please select between 1 and 3 bartenders.", parent=self)
            return
        
        self.callback(selected_workers)
        self.destroy()