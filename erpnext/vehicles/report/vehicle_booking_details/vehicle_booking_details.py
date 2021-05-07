# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _, scrub, unscrub
from frappe.utils import cint, flt, cstr, getdate, nowdate
from erpnext.stock.report.stock_ledger.stock_ledger import get_item_group_condition
from frappe.desk.query_report import group_report_data


class VehicleBookingDetailsReport(object):
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})

		self.filters.from_date = getdate(self.filters.from_date or nowdate())
		self.filters.to_date = getdate(self.filters.to_date or nowdate())

		self.show_item_name = frappe.defaults.get_global_default('item_naming_by') != "Item Name"
		self.show_customer_name = frappe.defaults.get_global_default('cust_master_name') == "Naming Series"

		self.group_by = []

	def run(self):
		self.get_data()
		self.prepare_data()

		data = self.get_grouped_data()
		columns = self.get_columns()

		return columns, data

	def get_data(self):
		filter_conditions = self.get_conditions()

		self.data = frappe.db.sql("""
			select m.name, m.transaction_date, m.vehicle_delivered_date,
				m.customer, m.financer, m.customer_name, m.finance_type, m.tax_id, m.tax_cnic, m.supplier,
				m.item_code, m.item_name, m.previous_item_code, item.variant_of, item.item_group, item.brand,
				m.allocation_period, m.delivery_period, m.priority, m.allocation_title,
				m.contact_person, m.contact_mobile, m.contact_phone,
				m.color_1, m.color_2, m.color_3, m.previous_color,
				1 as qty, m.invoice_total, m.payment_adjustment,
				m.status,
				m.customer_advance, m.supplier_advance
			from `tabVehicle Booking Order` m
			inner join `tabItem` item on item.name = m.item_code
			left join `tabVehicle Allocation Period` ap on ap.name = m.allocation_period
			left join `tabVehicle Allocation Period` dp on dp.name = m.delivery_period
			where m.docstatus = 1 {conditions}
			order by {order_by}
		""".format(conditions=filter_conditions, order_by=self.order_by), self.filters, as_dict=1)

		return self.data

	def prepare_data(self):
		for d in self.data:
			d.reference_type = 'Vehicle Booking Order'
			d.reference = d.name

			d.disable_item_formatter = cint(self.show_item_name)

			is_leased = d.financer and d.finance_type == "Leased"

			d.vehicle_color = d.vehicle_color or d.color_1 or d.color_2 or d.color_3
			d.tax_cnic_ntn = d.tax_id or d.tax_cnic if is_leased else d.tax_cnic or d.tax_id
			d.contact_number = d.contact_mobile or d.contact_phone

			d.original_item_code = d.get('previous_item_code') or d.item_code

		return self.data

	def get_grouped_data(self):
		data = self.data

		self.group_by = [None]
		for i in range(3):
			group_label = self.filters.get("group_by_" + str(i + 1), "").replace("Group by ", "")

			if not group_label or group_label == "Ungrouped":
				continue
			elif group_label == "Variant":
				group_field = "item_code"
			elif group_label == "Model":
				group_field = "variant_of"
			else:
				group_field = scrub(group_label)

			self.group_by.append(group_field)

		if len(self.group_by) <= 1:
			return data

		return group_report_data(data, self.group_by, calculate_totals=self.calculate_group_totals)

	def calculate_group_totals(self, data, group_field, group_value, grouped_by):
		totals = frappe._dict()

		# Copy grouped by into total row
		for f, g in grouped_by.items():
			totals[f] = g

		# Sum
		sum_fields = ['invoice_total', 'qty']
		for f in sum_fields:
			totals[f] = sum([flt(d.get(f)) for d in data])

		group_reference_doctypes = {
			"item_code": "Item",
			"variant_of": "Item",
			"status": None,
		}

		# set reference field
		reference_field = group_field[0] if isinstance(group_field, (list, tuple)) else group_field
		reference_dt = group_reference_doctypes.get(reference_field, unscrub(cstr(reference_field)))
		totals['reference_type'] = reference_dt
		if not group_field:
			totals['reference'] = "'Total'"
		elif not reference_dt:
			totals['reference'] = "'{0}'".format(grouped_by.get(reference_field))
		else:
			totals['reference'] = grouped_by.get(reference_field)

		if not group_field and self.group_by == [None]:
			totals['reference'] = "'Total'"

		# set item_code from model
		if "variant_of" in grouped_by:
			totals['item_code'] = totals['variant_of']

		return totals

	def get_conditions(self):
		conditions = []

		if self.filters.date_type == "Vehicle Delivered Date":
			self.order_by = "m.vehicle_delivered_date, m.transaction_date, m.name"
			conditions.append('m.vehicle_delivered_date between %(from_date)s and %(to_date)s')
		elif self.filters.date_type == "Delivery Period":
			self.order_by = "dp.from_date, m.transaction_date, m.name"
			conditions.append('((dp.from_date <= %(to_date)s) and (dp.to_date >= %(from_date)s))')
		else:
			self.order_by = "m.transaction_date, m.name"
			conditions.append('m.transaction_date between %(from_date)s and %(to_date)s')

		if self.filters.company:
			conditions.append("m.company = %(company)s")

		if self.filters.variant_of:
			conditions.append("item.variant_of = %(variant_of)s")

		if self.filters.item_code:
			conditions.append("item.name = %(item_code)s")

		if self.filters.item_group:
			conditions.append(get_item_group_condition(self.filters.item_group))

		if self.filters.brand:
			conditions.append("item.brand = %(brand)s")

		if self.filters.customer:
			conditions.append("vbo.customer = %(customer)s")

		if self.filters.financer:
			conditions.append("vbo.financer = %(financer)s")

		if self.filters.supplier:
			conditions.append("m.supplier = %(supplier)s")

		if self.filters.priority:
			conditions.append("m.priority = 1")

		return "and {}".format(" and ".join(conditions)) if conditions else ""


	def get_columns(self):
		columns = []

		if self.group_by:
			columns.append({"label": _("Reference"), "fieldname": "reference", "fieldtype": "Dynamic Link", "options": "reference_type", "width": 200})
		else:
			columns.append({"label": _("Booking #"), "fieldname": "name", "fieldtype": "Link", "options": "Vehicle Booking Order", "width": 105})

		columns += [
			{"label": _("Booking Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 100},
			{"label": _("Delivery Date"), "fieldname": "vehicle_delivered_date", "fieldtype": "Date", "width": 100},
			# {"label": _("Customer (User)"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 100},
			# {"label": _("Financer"), "fieldname": "financer", "fieldtype": "Link", "options": "Customer", "width": 100},
			{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 200},
			{"label": _("Variant Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
			{"label": _("Variant Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 150},
			{"label": _("Color"), "fieldname": "vehicle_color", "fieldtype": "Link", "options": "Vehicle Color", "width": 120},
			{"label": _("Delivery Period"), "fieldname": "delivery_period", "fieldtype": "Link", "options": "Vehicle Allocation Period", "width": 110},
			{"label": _("Units"), "fieldname": "qty", "fieldtype": "Int", "width": 50},
			{"label": _("Invoice Total"), "fieldname": "invoice_total", "fieldtype": "Currency", "width": 120},
			{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 140},
			{"label": _("CNIC/NTN"), "fieldname": "tax_cnic_ntn", "fieldtype": "Data", "width": 110},
			{"label": _("Contact"), "fieldname": "contact_number", "fieldtype": "Data", "width": 110},
			{"label": _("Allocation"), "fieldname": "allocation_title", "fieldtype": "Data", "width": 200},
			{"label": _("Previous Variant"), "fieldname": "previous_item_code", "fieldtype": "Link", "options": "Item", "width": 120},
			{"label": _("Previous Color"), "fieldname": "previous_color", "fieldtype": "Link", "options": "Vehicle Color", "width": 120},
			{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Data", "width": 100},
		]

		return columns


def execute(filters=None):
	return VehicleBookingDetailsReport(filters).run()
