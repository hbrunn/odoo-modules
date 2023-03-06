from odoo import fields, models


class BitcoinPaymentAcquirer(models.Model):
    _inherit = "payment.acquirer"

    provider = fields.Selection(
        selection_add=[("bitcoin", "Bitcoin")], ondelete={"bitcoin": "set default"}
    )
    deadline = fields.Float(
        help="Add a deadline to Bitcoin payments within which the payment should be made.",
    )

    def _get_default_payment_method_id(self):
        self.ensure_one()
        if self.provider == "bitcoin":
            return self.env.ref("payment_bitcoin.payment_method_bitcoin").id
        return super()._get_default_payment_method_id()
