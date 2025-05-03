import mariadb
import pandas as pd
import sys
import os
from PyQt6 import uic
from fpdf import FPDF
from decimal import Decimal
from db.config import db_config
from PyQt6.QtWidgets import (
    QMainWindow, QApplication, QCalendarWidget, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QProgressDialog
)
from PyQt6.QtCore import QDate, Qt, QThread, pyqtSignal # for handle dates and
#enable communication between threads and the main UI


class SalesHistoryWindow(QMainWindow):
    def __init__(self, user_id, db_config, dashboard_window):
        super().__init__()
        uic.loadUi("ui/sales_history.ui", self)

        self.user_id = user_id
        self.db_config = db_config
        self.dashboard_window = dashboard_window

        self.calendar = self.findChild(QCalendarWidget, "calendarWidget")
        self.sales_table = self.findChild(QTableWidget, "salesTable")
        self.export_excel_button = self.findChild(QPushButton, "exportExcelButton")
        self.export_pdf_button = self.findChild(QPushButton, "exportPdfButton")
        self.back_button = self.findChild(QPushButton, "backButton")

        self.sales_table.setColumnCount(5)
        self.sales_table.setHorizontalHeaderLabels([
            "Order ID", "Product Name", "Quantity", "Total Sales", "Sales Date"
        ])

        self.first_load = True

        self.calendar.selectionChanged.connect(self.load_sales)
        self.export_excel_button.clicked.connect(self.export_to_excel)
        self.export_pdf_button.clicked.connect(self.export_to_pdf)
        self.back_button.clicked.connect(self.go_back)

        self.calendar.setSelectedDate(QDate.currentDate())
        self.calendar.setCurrentPage(QDate.currentDate().year(), QDate.currentDate().month())

        self.load_sales_for_today()

    def go_back(self):
        self.dashboard_window.show()
        self.close()

    def load_sales_for_today(self):
        selected_date = QDate.currentDate().toString("yyyy-MM-dd")
        self.load_sales(selected_date)

    def load_sales(self, selected_date=None):
        if selected_date is None:
            selected_date = self.calendar.selectedDate().toString("yyyy-MM-dd")

        self.loading_dialog = QProgressDialog("Loading sales data...", "Cancel", 0, 0, self)
        self.loading_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.loading_dialog.setCancelButton(None)
        self.loading_dialog.setValue(0)
        self.loading_dialog.show()

        self.thread = SalesLoaderThread(self.user_id, selected_date, self.db_config)
        self.thread.finished.connect(self.on_sales_data_loaded)
        self.thread.start()

    def on_sales_data_loaded(self, sales_data):
        self.loading_dialog.close()

        self.sales_table.setRowCount(0)

        if not sales_data:
            QMessageBox.warning(self, "No Data", f"No sales data found for {self.calendar.selectedDate().toString('yyyy-MM-dd')}.")
            return

        order_sales = {}
        for sale in sales_data:
            order_id, product_name, quantity, total_price, order_datetime = sale
            total_price = Decimal(total_price)

            if order_id not in order_sales:
                order_sales[order_id] = {"products": [], "total_sales": Decimal('0.00')}

            order_sales[order_id]["products"].append((product_name, quantity))
            order_sales[order_id]["total_sales"] += total_price

        for order_id, details in order_sales.items():
            products = ", ".join([p[0] for p in details["products"]])
            quantities = ", ".join([str(p[1]) for p in details["products"]])
            total_sales = details["total_sales"]

            row_position = self.sales_table.rowCount()
            self.sales_table.insertRow(row_position)
            self.sales_table.setItem(row_position, 0, QTableWidgetItem(str(order_id)))
            self.sales_table.setItem(row_position, 1, QTableWidgetItem(products))
            self.sales_table.setItem(row_position, 2, QTableWidgetItem(quantities))
            self.sales_table.setItem(row_position, 3, QTableWidgetItem(f"{total_sales:.2f}"))
            self.sales_table.setItem(row_position, 4, QTableWidgetItem(str(order_datetime.date())))

    def export_to_excel(self):
        if self.sales_table.rowCount() == 0:
            QMessageBox.warning(self, "No Data", "No sales data available to export.")
            return

        selected_date = self.calendar.selectedDate().toString("yyyy-MM-dd")
        filename = f"sales_history_{selected_date}.xlsx"
        path = os.path.join(os.path.expanduser("~"), filename)

        try:
            data = []
            for row in range(self.sales_table.rowCount()):
                row_data = []
                for column in range(self.sales_table.columnCount()):
                    item = self.sales_table.item(row, column)
                    row_data.append(item.text() if item else "")
                data.append(row_data)

            df = pd.DataFrame(data, columns=[
                "Order ID", "Product Name", "Quantity", "Total Sales", "Sales Date"
            ])
            df.to_excel(path, index=False)

            QMessageBox.information(self, "Export Successful", f"Sales history exported to Excel:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def export_to_pdf(self):
        if self.sales_table.rowCount() == 0:
            QMessageBox.warning(self, "No Data", "No sales data available to export.")
            return

        selected_date = self.calendar.selectedDate().toString("yyyy-MM-dd")
        filename = f"sales_history_{selected_date}.pdf"
        path = os.path.join(os.path.expanduser("~"), filename)

        try:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.set_font("Arial", size=10)

            col_widths = [30, 40, 30, 30, 40]
            headers = ["Order ID", "Product Name", "Quantity", "Total Sales", "Sales Date"]

            for i, header in enumerate(headers):
                pdf.cell(col_widths[i], 10, header, 1)
            pdf.ln()

            for row in range(self.sales_table.rowCount()):
                for col in range(self.sales_table.columnCount()):
                    item = self.sales_table.item(row, col)
                    text = item.text() if item else ""
                    pdf.cell(col_widths[col], 10, text, 1)
                pdf.ln()

            pdf.output(path)
            QMessageBox.information(self, "Export Successful", f"Sales history exported to PDF:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))


class SalesLoaderThread(QThread):
    finished = pyqtSignal(list)

    def __init__(self, user_id, selected_date, db_config):
        super().__init__()
        self.user_id = user_id
        self.selected_date = selected_date
        self.db_config = db_config

    def run(self):
        try:
            conn = mariadb.connect(**self.db_config)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT o.orderId, p.productName, od.quantity, od.totalPrice, o.orderDateTime
                FROM order_details od
                JOIN orders o ON od.orderId = o.orderId
                JOIN products p ON od.productId = p.productId
                WHERE o.userId = ? AND DATE(o.orderDateTime) = ?
            """, (self.user_id, self.selected_date))

            sales_data = cursor.fetchall()

        except Exception as e:
            sales_data = []
        finally:
            if conn:
                cursor.close()
                conn.close()
            self.finished.emit(sales_data)


class DashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi("ui/dashboard.ui", self)

        self.sales_history_button = self.findChild(QPushButton, "salesHistoryButton")

        self.sales_history_button.clicked.connect(self.open_sales_history)

    def open_sales_history(self):
        self.hide()
        user_id = 1
        window = SalesHistoryWindow(user_id, db_config, self)
        window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard_window = DashboardWindow()
    dashboard_window.show()
    sys.exit(app.exec())
