# Copyright 2017 Okia SPRL (https://okia.be)
# Copyright 2020 Tecnativa - Manuel Calero
# Copyright 2020 Tecnativa - João Marques
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import re
from datetime import datetime

from dateutil import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import Form

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestCreditControlRun(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.env = cls.env(
            context=dict(
                cls.env.context,
                mail_create_nolog=True,
                mail_create_nosubscribe=True,
                mail_notrack=True,
                no_reset_password=True,
                tracking_disable=True,
            )
        )
        cls.env.user.groups_id |= cls.env.ref(
            "account_credit_control.group_account_credit_control_manager"
        )
        journal = cls.company_data["default_journal_sale"]
        account_type_rec = cls.env.ref("account.data_account_type_receivable")
        account = cls.env["account.account"].create(
            {
                "code": "TEST430001",
                "name": "Clients (test)",
                "user_type_id": account_type_rec.id,
                "reconcile": True,
            }
        )
        tag_operation = cls.env.ref("account.account_tag_operating")
        account_type_inc = cls.env.ref("account.data_account_type_revenue")
        analytic_account = cls.env["account.account"].create(
            {
                "code": "TEST701001",
                "name": "Ventes en Belgique (test)",
                "user_type_id": account_type_inc.id,
                "reconcile": True,
                "tag_ids": [(6, 0, [tag_operation.id])],
            }
        )
        payment_term = cls.env.ref("account.account_payment_term_immediate")
        product = cls.env["product.product"].create({"name": "Product test"})
        cls.policy = cls.env.ref("account_credit_control.credit_control_3_time")
        cls.policy.write({"account_ids": [(6, 0, [account.id])]})

        # There is a bug with Odoo ...
        # The field "credit_policy_id" is considered as an "old field" and
        # the field property_account_receivable_id like a "new field"
        # The ORM will create the record with old field
        # and update the record with new fields.
        # However constrains are applied after the first creation.
        partner = cls.env["res.partner"].create(
            {"name": "Partner", "property_account_receivable_id": account.id}
        )
        partner.credit_policy_id = cls.policy.id
        date_invoice = datetime.today() - relativedelta.relativedelta(years=1)

        # Create an invoice
        invoice_form = Form(
            cls.env["account.move"].with_context(
                default_move_type="out_invoice", check_move_validity=False
            )
        )
        invoice_form.invoice_date = date_invoice
        invoice_form.invoice_date_due = date_invoice
        invoice_form.partner_id = partner
        invoice_form.journal_id = journal
        invoice_form.invoice_payment_term_id = payment_term
        with invoice_form.invoice_line_ids.new() as invoice_line_form:
            invoice_line_form.product_id = product
            invoice_line_form.quantity = 1
            invoice_line_form.price_unit = 500
            invoice_line_form.account_id = analytic_account
            invoice_line_form.tax_ids.clear()
        cls.invoice = invoice_form.save()
        cls.invoice.action_post()

    def test_check_run_date(self):
        """
        Create a control run older than the last control run
        """
        control_run = self.env["credit.control.run"].create(
            {"date": fields.Date.today(), "policy_ids": [(6, 0, [self.policy.id])]}
        )

        with self.assertRaises(UserError):
            today = datetime.today()
            previous_date = today - relativedelta.relativedelta(days=15)
            previous_date_str = fields.Date.to_string(previous_date)
            control_run._check_run_date(previous_date_str)

    def test_generate_credit_lines(self):
        """
        Test the method generate_credit_lines
        """
        control_run = self.env["credit.control.run"].create(
            {"date": fields.Date.today(), "policy_ids": [(6, 0, [self.policy.id])]}
        )

        control_run.with_context(lang="en_US").generate_credit_lines()

        self.assertEqual(len(self.invoice.credit_control_line_ids), 1)
        self.assertEqual(control_run.state, "done")

        report_regex = (
            r'<p>Policy "<b>%s</b>" has generated <b>'
            r"\d+ Credit Control Lines.</b><br></p>" % self.policy.name
        )
        regex_result = re.match(report_regex, control_run.report)
        self.assertIsNotNone(regex_result)

    def test_multi_credit_control_run(self):
        """
        Generate several control run
        """

        six_months = datetime.today() - relativedelta.relativedelta(months=6)
        six_months_str = fields.Date.to_string(six_months)
        three_months = datetime.today() - relativedelta.relativedelta(months=2)
        three_months_str = fields.Date.to_string(three_months)

        # First run
        first_control_run = self.env["credit.control.run"].create(
            {"date": six_months_str, "policy_ids": [(6, 0, [self.policy.id])]}
        )
        first_control_run.with_context(lang="en_US").generate_credit_lines()
        self.assertEqual(len(self.invoice.credit_control_line_ids), 1)

        # Second run
        second_control_run = self.env["credit.control.run"].create(
            {"date": three_months_str, "policy_ids": [(6, 0, [self.policy.id])]}
        )
        second_control_run.with_context(lang="en_US").generate_credit_lines()
        self.assertEqual(len(self.invoice.credit_control_line_ids), 2)

        # Last run
        last_control_run = self.env["credit.control.run"].create(
            {"date": fields.Date.today(), "policy_ids": [(6, 0, [self.policy.id])]}
        )
        last_control_run.with_context(lang="en_US").generate_credit_lines()
        self.assertEqual(len(self.invoice.credit_control_line_ids), 3)

    def test_wiz_print_lines(self):
        """
        Test the wizard Credit Control Printer
        """
        control_run = self.env["credit.control.run"].create(
            {"date": fields.Date.today(), "policy_ids": [(6, 0, [self.policy.id])]}
        )

        control_run.with_context(lang="en_US").generate_credit_lines()

        self.assertTrue(len(self.invoice.credit_control_line_ids), 1)
        self.assertEqual(control_run.state, "done")

        report_regex = (
            r'<p>Policy "<b>%s</b>" has generated <b>'
            r"\d+ Credit Control Lines.</b><br></p>" % self.policy.name
        )
        regex_result = re.match(report_regex, control_run.report)
        self.assertIsNotNone(regex_result)

        # Mark lines to be send
        control_lines = self.invoice.credit_control_line_ids
        marker = self.env["credit.control.marker"].create(
            {"name": "to_be_sent", "line_ids": [(6, 0, control_lines.ids)]}
        )
        marker.mark_lines()

        # Create wizard
        emailer_obj = self.env["credit.control.emailer"]
        wiz_emailer = emailer_obj.create({})
        wiz_emailer.line_ids = control_lines

        # Send email
        wiz_emailer.email_lines()

    def test_wiz_credit_control_emailer(self):
        """
        Test the wizard credit control emailer
        """
        control_run = self.env["credit.control.run"].create(
            {"date": fields.Date.today(), "policy_ids": [(6, 0, [self.policy.id])]}
        )

        control_run.with_context(lang="en_US").generate_credit_lines()

        self.assertTrue(len(self.invoice.credit_control_line_ids), 1)
        self.assertEqual(control_run.state, "done")

        report_regex = (
            r'<p>Policy "<b>%s</b>" has generated <b>'
            r"\d+ Credit Control Lines.</b><br></p>" % self.policy.name
        )
        regex_result = re.match(report_regex, control_run.report)
        self.assertIsNotNone(regex_result)

        # Mark lines to be send
        control_lines = self.invoice.credit_control_line_ids
        marker = self.env["credit.control.marker"].create(
            {"name": "to_be_sent", "line_ids": [(6, 0, control_lines.ids)]}
        )
        marker.mark_lines()

        # Create wizard
        printer_obj = self.env["credit.control.printer"]
        wiz_printer = printer_obj.with_context(
            active_model="credit.control.line", active_ids=control_lines.ids
        ).create({})
        wiz_printer.print_lines()
