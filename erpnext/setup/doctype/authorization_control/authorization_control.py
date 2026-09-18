# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _, session
from frappe.query_builder.functions import Coalesce
from frappe.utils import comma_or, cstr, flt, has_common

from erpnext.utilities.transaction_base import TransactionBase


class AuthorizationControl(TransactionBase):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

	# end: auto-generated types

	def get_appr_user_role(self, det, doctype_name, total, based_on, condition, company):
		amt_list, appr_users, appr_roles = [], [], []
		if det:
			for x in det:
				amt_list.append(flt(x[0]))
			max_amount = max(amt_list)

			auth_rule = frappe.qb.DocType("Authorization Rule")
			base_condition = (
				(auth_rule.transaction == doctype_name)
				& ((auth_rule.value == flt(max_amount)) | (auth_rule.value > total))
				& (auth_rule.docstatus != 2)
				& (auth_rule.based_on == based_on)
				& condition
			)

			def get_approvers(company_condition):
				return (
					frappe.qb.from_(auth_rule)
					.select(auth_rule.approving_user, auth_rule.approving_role)
					.where(base_condition & company_condition)
				).run()

			app_dtl = get_approvers(auth_rule.company == company)
			if not app_dtl:
				app_dtl = get_approvers(Coalesce(auth_rule.company, "") == "")

			for d in app_dtl:
				if d[0]:
					appr_users.append(d[0])
				if d[1]:
					appr_roles.append(d[1])

			if not has_common(appr_roles, frappe.get_roles()) and not has_common(
				appr_users, [session["user"]]
			):
				frappe.msgprint(_("Not authorized since {0} exceeds limits").format(_(based_on)))
				frappe.throw(_("Can be approved by {0}").format(comma_or(appr_roles + appr_users)))

	def validate_auth_rule(self, doctype_name, total, based_on, condition, company, master_name=""):
		auth_rule = frappe.qb.DocType("Authorization Rule")
		base_condition = (
			(auth_rule.transaction == doctype_name)
			& (auth_rule.value <= total)
			& (auth_rule.based_on == based_on)
			& (auth_rule.docstatus != 2)
		)

		def get_rule_values(scope_condition, company_condition):
			return (
				frappe.qb.from_(auth_rule)
				.select(auth_rule.value)
				.where(base_condition & scope_condition & company_condition)
			).run()

		def get_company_rule_values(scope_condition):
			values = get_rule_values(scope_condition, auth_rule.company == company)
			if not values:
				values = get_rule_values(scope_condition, Coalesce(auth_rule.company, "") == "")
			return values

		chk = 1
		if based_on in ["Itemwise Discount", "Item Group wise Discount"]:
			item_condition = condition & (auth_rule.master_name == cstr(master_name))
			itemwise_exists = get_company_rule_values(item_condition)

			if itemwise_exists:
				self.get_appr_user_role(
					itemwise_exists, doctype_name, total, based_on, item_condition, company
				)
				chk = 0
		if chk == 1:
			if based_on in ["Itemwise Discount", "Item Group wise Discount"]:
				condition &= Coalesce(auth_rule.master_name, "") == ""

			appr = get_company_rule_values(condition)
			self.get_appr_user_role(appr, doctype_name, total, based_on, condition, company)

	def bifurcate_based_on_type(self, doctype_name, total, av_dis, based_on, doc_obj, val, company):
		auth_rule = frappe.qb.DocType("Authorization Rule")
		auth_value = av_dis

		if val == 1:
			condition = auth_rule.system_user == session["user"]
		elif val == 2:
			condition = auth_rule.system_role.isin(frappe.get_roles())
		else:
			condition = (Coalesce(auth_rule.system_user, "") == "") & (
				Coalesce(auth_rule.system_role, "") == ""
			)

		if based_on == "Grand Total":
			auth_value = total
		elif based_on == "Customerwise Discount":
			if doc_obj:
				if doc_obj.doctype == "Sales Invoice":
					customer = doc_obj.customer
				else:
					customer = doc_obj.customer_name
				condition = auth_rule.master_name == customer
		if based_on == "Itemwise Discount":
			if doc_obj:
				for t in doc_obj.get("items"):
					self.validate_auth_rule(
						doctype_name, t.discount_percentage, based_on, condition, company, t.item_code
					)
		elif based_on == "Item Group wise Discount":
			if doc_obj:
				for t in doc_obj.get("items"):
					self.validate_auth_rule(
						doctype_name, t.discount_percentage, based_on, condition, company, t.item_group
					)
		else:
			self.validate_auth_rule(doctype_name, auth_value, based_on, condition, company)

	def validate_approving_authority(self, doctype_name, company, total, doc_obj=""):
		if not frappe.db.count("Authorization Rule"):
			return

		av_dis = 0
		if doc_obj:
			price_list_rate, base_rate = 0, 0
			for d in doc_obj.get("items"):
				if d.base_rate:
					price_list_rate += (flt(d.base_price_list_rate) or flt(d.base_rate)) * flt(d.qty)
					base_rate += flt(d.base_rate) * flt(d.qty)
			if doc_obj.get("discount_amount"):
				base_rate -= flt(doc_obj.discount_amount)

			if price_list_rate:
				av_dis = 100 - flt(base_rate * 100 / price_list_rate)

		final_based_on = [
			"Grand Total",
			"Average Discount",
			"Customerwise Discount",
			"Itemwise Discount",
			"Item Group wise Discount",
		]

		auth_rule = frappe.qb.DocType("Authorization Rule")

		# Check for authorization set for individual user
		based_on = [
			x[0]
			for x in (
				frappe.qb.from_(auth_rule)
				.select(auth_rule.based_on)
				.distinct()
				.where(
					(auth_rule.transaction == doctype_name)
					& (auth_rule.system_user == session["user"])
					& ((auth_rule.company == company) | (Coalesce(auth_rule.company, "") == ""))
					& (auth_rule.docstatus != 2)
				)
			).run()
		]

		for d in based_on:
			self.bifurcate_based_on_type(doctype_name, total, av_dis, d, doc_obj, 1, company)

		# Remove user specific rules from global authorization rules
		for r in based_on:
			if r in final_based_on and r not in [
				"Itemwise Discount",
				"Item Group wise Discount",
			]:
				final_based_on.remove(r)

		# Check for authorization set on particular roles
		based_on = [
			x[0]
			for x in (
				frappe.qb.from_(auth_rule)
				.select(auth_rule.based_on)
				.where(
					(auth_rule.transaction == doctype_name)
					& auth_rule.system_role.isin(frappe.get_roles())
					& auth_rule.based_on.isin(final_based_on)
					& ((auth_rule.company == company) | (Coalesce(auth_rule.company, "") == ""))
					& (auth_rule.docstatus != 2)
				)
			).run()
		]

		for d in based_on:
			self.bifurcate_based_on_type(doctype_name, total, av_dis, d, doc_obj, 2, company)

		# Remove role specific rules from global authorization rules
		for r in based_on:
			if r in final_based_on and r not in [
				"Itemwise Discount",
				"Item Group wise Discount",
			]:
				final_based_on.remove(r)

		# Check for global authorization
		for g in final_based_on:
			self.bifurcate_based_on_type(doctype_name, total, av_dis, g, doc_obj, 0, company)

	def get_value_based_rule(self, doctype_name, employee, total_claimed_amount, company):
		auth_rule = frappe.qb.DocType("Authorization Rule")
		emp = frappe.qb.DocType("Employee")

		def emp_designation():
			# fresh subquery per use to avoid sharing a pypika builder across queries
			return frappe.qb.from_(emp).select(emp.designation).where(emp.name == employee)

		val_lst = []
		val = (
			frappe.qb.from_(auth_rule)
			.select(auth_rule.value)
			.where(
				(auth_rule.transaction == doctype_name)
				& ((auth_rule.to_emp == employee) | auth_rule.to_designation.isin(emp_designation()))
				& (Coalesce(auth_rule.value, 0) < total_claimed_amount)
				& (auth_rule.company == company)
				& (auth_rule.docstatus != 2)
			)
		).run()

		if not val:
			val = (
				frappe.qb.from_(auth_rule)
				.select(auth_rule.value)
				.where(
					(auth_rule.transaction == doctype_name)
					& ((auth_rule.to_emp == employee) | auth_rule.to_designation.isin(emp_designation()))
					& (Coalesce(auth_rule.value, 0) < total_claimed_amount)
					& (Coalesce(auth_rule.company, "") == "")
					& (auth_rule.docstatus != 2)
				)
			).run()

		if val:
			val_lst = [y[0] for y in val]
		else:
			val_lst.append(0)

		max_val = max(val_lst)
		rule = (
			frappe.qb.from_(auth_rule)
			.select(
				auth_rule.name,
				auth_rule.to_emp,
				auth_rule.to_designation,
				auth_rule.approving_role,
				auth_rule.approving_user,
			)
			.where(
				(auth_rule.transaction == doctype_name)
				& (auth_rule.company == company)
				& ((auth_rule.to_emp == employee) | auth_rule.to_designation.isin(emp_designation()))
				& (Coalesce(auth_rule.value, 0) == flt(max_val))
				& (auth_rule.docstatus != 2)
			)
		).run(as_dict=1)

		if not rule:
			rule = (
				frappe.qb.from_(auth_rule)
				.select(
					auth_rule.name,
					auth_rule.to_emp,
					auth_rule.to_designation,
					auth_rule.approving_role,
					auth_rule.approving_user,
				)
				.where(
					(auth_rule.transaction == doctype_name)
					& (Coalesce(auth_rule.company, "") == "")
					& ((auth_rule.to_emp == employee) | auth_rule.to_designation.isin(emp_designation()))
					& (Coalesce(auth_rule.value, 0) == flt(max_val))
					& (auth_rule.docstatus != 2)
				)
			).run(as_dict=1)

		return rule
