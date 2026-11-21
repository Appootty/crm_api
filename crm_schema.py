"""Database tables and views used by the loader.
Copied from generate_crm_data.py (SCHEMA and VIEWS). If the schema changes there, copy it here again."""

SCHEMA = {'users': 'id INTEGER PRIMARY KEY, name TEXT, role TEXT, email TEXT, phone TEXT, warehouse_id INTEGER, '
          'active INTEGER',
 'warehouses': 'id INTEGER PRIMARY KEY, name TEXT, city TEXT, manager_id INTEGER',
 'customer_classes': 'class_type TEXT PRIMARY KEY, discount_pct REAL, default_credit_amount REAL, '
                     'default_credit_days INTEGER',
 'suppliers': 'id INTEGER PRIMARY KEY, name TEXT, city TEXT, phone TEXT, payment_terms_days INTEGER',
 'customers': 'id INTEGER PRIMARY KEY, code TEXT, name TEXT, category TEXT, registration_id TEXT, trn_gst_no '
              'TEXT, street TEXT, place TEXT, city TEXT, state_province TEXT, latitude REAL, longitude REAL, '
              'email TEXT, phone TEXT, alt_phone TEXT, contact_person TEXT, comments TEXT, class_type TEXT, '
              'max_credit_amount REAL, max_credit_period_days INTEGER, status TEXT, salesman_id INTEGER, '
              'home_warehouse_id INTEGER, wallet_balance REAL, created_at TEXT',
 'items': 'id INTEGER PRIMARY KEY, sku TEXT, name TEXT, brand TEXT, category TEXT, unit TEXT, cost_price '
          'REAL, sale_price REAL, reorder_level INTEGER, supplier_id INTEGER, active INTEGER',
 'stock': 'item_id INTEGER, warehouse_id INTEGER, quantity INTEGER, PRIMARY KEY (item_id, warehouse_id)',
 'sales_orders': 'id INTEGER PRIMARY KEY, order_no TEXT, invoice_no TEXT, doc_type TEXT, customer_id '
                 'INTEGER, salesman_id INTEGER, warehouse_id INTEGER, order_date TEXT, delivered_date TEXT, '
                 'due_date TEXT, status TEXT, payment_status TEXT, source TEXT, subtotal REAL, discount '
                 'REAL, tax_amount REAL, total REAL, paid_amount REAL, notes TEXT',
 'sales_order_lines': 'id INTEGER PRIMARY KEY, order_id INTEGER, item_id INTEGER, quantity INTEGER, '
                      'unit_price REAL, discount_pct REAL, line_total REAL',
 'payments': 'id INTEGER PRIMARY KEY, order_id INTEGER, customer_id INTEGER, payment_date TEXT, amount REAL, '
             'method TEXT, reference TEXT, collected_by INTEGER',
 'wallet_ledger': 'id INTEGER PRIMARY KEY, customer_id INTEGER, entry_date TEXT, entry_type TEXT, amount '
                  'REAL, order_id INTEGER, return_id INTEGER, balance_after REAL',
 'deliveries': 'id INTEGER PRIMARY KEY, order_id INTEGER, driver_id INTEGER, assigned_at TEXT, delivered_at '
               'TEXT, status TEXT, attempts INTEGER, failure_reason TEXT',
 'order_edit_history': 'id INTEGER PRIMARY KEY, order_id INTEGER, line_id INTEGER, field TEXT, old_value '
                       'TEXT, new_value TEXT, edited_by INTEGER, edited_at TEXT',
 'approval_requests': 'id INTEGER PRIMARY KEY, request_type TEXT, customer_id INTEGER, order_id INTEGER, '
                      'requested_by INTEGER, approved_by INTEGER, status TEXT, created_at TEXT, decided_at '
                      'TEXT, details TEXT',
 'visits': 'id INTEGER PRIMARY KEY, customer_id INTEGER, salesman_id INTEGER, planned_date TEXT, status '
           'TEXT, outcome TEXT, order_taken INTEGER, notes TEXT',
 'activities': 'id INTEGER PRIMARY KEY, user_id INTEGER, customer_id INTEGER, activity_type TEXT, '
               'activity_date TEXT, order_id INTEGER, details TEXT',
 'sales_returns': 'id INTEGER PRIMARY KEY, return_no TEXT, order_id INTEGER, customer_id INTEGER, '
                  'warehouse_id INTEGER, return_date TEXT, status TEXT, reason TEXT, credit_amount REAL, '
                  'decided_at TEXT',
 'sales_return_lines': 'id INTEGER PRIMARY KEY, return_id INTEGER, order_line_id INTEGER, item_id INTEGER, '
                       'quantity INTEGER, amount REAL',
 'purchase_orders': 'id INTEGER PRIMARY KEY, po_no TEXT, supplier_id INTEGER, warehouse_id INTEGER, '
                    'order_date TEXT, expected_date TEXT, status TEXT, total REAL',
 'purchase_lines': 'id INTEGER PRIMARY KEY, po_id INTEGER, item_id INTEGER, quantity INTEGER, unit_cost REAL',
 'expenses': 'id INTEGER PRIMARY KEY, warehouse_id INTEGER, expense_date TEXT, category TEXT, amount REAL, '
             'notes TEXT',
 'synthetic_notes': 'id INTEGER PRIMARY KEY, topic TEXT, detail TEXT'}

VIEWS = "\nCREATE VIEW v_outstanding_orders AS\nSELECT o.id AS order_id, o.invoice_no, c.name AS customer, c.class_type, o.salesman_id, o.delivered_date, o.due_date,\n       o.total, o.paid_amount, ROUND(o.total - o.paid_amount, 2) AS outstanding,\n       CAST(julianday((SELECT MAX(order_date) FROM sales_orders)) - julianday(o.due_date) AS INTEGER) AS days_overdue\nFROM sales_orders o JOIN customers c ON c.id = o.customer_id\nWHERE o.status = 'Delivered' AND o.total - o.paid_amount > 0.01;\nCREATE VIEW v_low_stock AS\nSELECT s.warehouse_id, i.id AS item_id, i.name, i.brand, s.quantity, i.reorder_level\nFROM stock s JOIN items i ON i.id = s.item_id WHERE s.quantity <= i.reorder_level AND i.active = 1;\nCREATE VIEW v_sales_monthly AS\nSELECT substr(order_date, 1, 7) AS month, warehouse_id, COUNT(*) AS orders, ROUND(SUM(total), 2) AS sales\nFROM sales_orders WHERE status NOT IN ('Cancelled', 'Rejected') GROUP BY 1, 2;\nCREATE VIEW v_customer_balance AS\nSELECT c.id AS customer_id, c.name, c.class_type, c.max_credit_amount,\n       ROUND(COALESCE(SUM(o.total - o.paid_amount), 0), 2) AS outstanding, c.wallet_balance\nFROM customers c LEFT JOIN sales_orders o ON o.customer_id = c.id AND o.status = 'Delivered' GROUP BY c.id;\nCREATE VIEW v_salesman_performance AS\nSELECT u.id AS salesman_id, u.name, substr(o.order_date, 1, 7) AS month, COUNT(*) AS orders,\n       ROUND(SUM(o.total), 2) AS sales, ROUND(SUM(o.paid_amount), 2) AS collected\nFROM sales_orders o JOIN users u ON u.id = o.salesman_id\nWHERE o.status NOT IN ('Cancelled', 'Rejected') GROUP BY 1, 2, 3;\n"
