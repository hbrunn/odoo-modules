from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class Segmentation(models.Model):
    """
    A segmentation is a tool to automatically assign categories on partners.
    These assignations are based on criterions.
    """

    _name = "crm.segmentation"
    _description = "Partner Segmentation"

    name = fields.Char(required=True, help="The name of the segmentation.")
    description = fields.Text()
    categ_id = fields.Many2one(
        "res.partner.category",
        "Partner Category",
        required=True,
        help="The partner category that will be  added to partners that match "
        "the segmentation criterions after computation.",
    )
    exclusif = fields.Boolean(
        "Exclusive",
        help="Check if the category is limited to partners that match the "
        "segmentation criterions.\nIf checked, remove the category from "
        "partners that doesn't match segmentation criterions",
    )
    state = fields.Selection(
        [("not running", "Not Running"), ("running", "Running")],
        "Execution Status",
        readonly=True,
        default="not running",
    )
    partner_id = fields.Integer("Max Partner ID processed", default=0)
    segmentation_line = fields.One2many(
        "crm.segmentation.line",
        "segmentation_id",
        "Criteria",
        required=True,
        copy=True,
    )
    sales_purchase_active = fields.Boolean(
        "Use The Sales Purchase Rules",
        help="Check if you want to use this tab as part of the segmentation "
        "rule. If not checked, the criteria beneath will be ignored",
    )
    answer_yes = fields.Many2many(
        "crm_profiling.answer",
        "profile_question_yes_rel",
        "profile",
        "answer",
        "Included Answers",
    )
    answer_no = fields.Many2many(
        "crm_profiling.answer",
        "profile_question_no_rel",
        "profile",
        "answer",
        "Excluded Answers",
    )
    parent_id = fields.Many2one("crm.segmentation", "Parent Profile")
    child_ids = fields.One2many("crm.segmentation", "parent_id", "Child Profiles")
    profiling_active = fields.Boolean(
        "Use The Profiling Rules",
        help="Check this box if you want to use this tab as part of the segmentation rule. "
        "If not checked, the criteria beneath will be ignored",
    )

    def process_continue(self, start=False):
        """
        :param self:      The current crm.segmentation.
        :param start:     start boolean flag
        """

        partner_obj = self.env["res.partner"]
        for seg in self:
            if start:
                if seg["exclusif"]:
                    self._cr.execute(
                        """
                        DELETE FROM res_partner_res_partner_category_rel
                        WHERE category_id=%s""",
                        (seg.categ_id.id,),
                    )
                    partner_obj.invalidate_cache(["category_id"])

            self._cr.execute("select id from res_partner order by id ")
            partners = [x[0] for x in self._cr.fetchall()]

            if seg.sales_purchase_active:
                to_remove_list = []
                lines = self.segmentation_line

                for pid in partners:
                    if not lines.test(pid):
                        to_remove_list.append(pid)
                for pid in to_remove_list:
                    partners.remove(pid)

            if seg.profiling_active:
                to_remove_list = []
                for pid in partners:
                    self.env.cr.execute(
                        """
                        SELECT DISTINCT(answer) FROM partner_question_rel
                        WHERE partner=%s""",
                        (pid,),
                    )
                    answers_ids = [x[0] for x in self.env.cr.fetchall()]

                    if not self.test_prof(pid, answers_ids):
                        to_remove_list.append(pid)
                for pid in to_remove_list:
                    partners.remove(pid)
            for partner in partner_obj.browse(partners):
                category_ids = partner.category_id.ids
                if seg.categ_id[0].ids not in category_ids:
                    self._cr.execute(
                        """
                        INSERT INTO res_partner_res_partner_category_rel
                        (category_id,partner_id)
                        VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                        (seg.categ_id.id, partner.id),
                    )
                    partner_obj.invalidate_cache(["category_id"], [partner.id])

            seg.write({"state": "not running", "partner_id": 0})
        return True

    def process_stop(self):
        return self.write({"state": "not running", "partner_id": 0})

    def process_start(self):
        """
        :param self:            The current crm.segmentation.
        """

        self.write({"state": "running", "partner_id": 0})
        return self.process_continue(start=True)

    @api.constrains("parent_id")
    def _check_parent_id(self):
        if not self._check_recursion():
            raise ValidationError(_("Error ! You cannot create recursive profiles."))

    def _get_parents(self):
        """
        :param self:       The current crm.segmentation.
        """

        ids_to_check = self.ids
        self.env.cr.execute(
            """
            SELECT distinct(parent_id)
            FROM crm_segmentation
            WHERE parent_id IS NOT NULL
            AND id IN %s""",
            (tuple(self.ids),),
        )

        parent_ids = [x[0] for x in self.env.cr.fetchall()]

        trigger = False
        for x in parent_ids:
            if x not in ids_to_check:
                ids_to_check.append(x)
                trigger = True

        if trigger:
            ids_to_check = self.browse(ids_to_check)._get_parents()

        return ids_to_check

    def _get_answers(self):
        query = """
            SELECT DISTINCT(answer)
            FROM profile_question_yes_rel
            WHERE profile IN %s"""

        self.env.cr.execute(query, (tuple(self.ids),))
        ans_yes = [x[0] for x in self.env.cr.fetchall()]

        query = """
            SELECT DISTINCT(answer)
            FROM profile_question_no_rel
            WHERE profile IN %s"""

        self.env.cr.execute(query, (tuple(self.ids),))
        ans_no = [x[0] for x in self.env.cr.fetchall()]

        return ans_yes, ans_no

    def test_prof(self, pid, answers_ids=None):
        ids_to_check = self._get_parents()
        yes_answers, no_answers = self.browse(ids_to_check)._get_answers()
        temp = True
        for y_ans in yes_answers:
            if y_ans not in answers_ids:
                temp = False
                break
        if temp:
            for ans in answers_ids:
                if ans in no_answers:
                    temp = False
                    break
        if temp:
            return True
        return False


class SegmentationLine(models.Model):
    """Segmentation line"""

    _name = "crm.segmentation.line"
    _description = "Segmentation line"

    name = fields.Char("Rule Name", required=True)
    segmentation_id = fields.Many2one("crm.segmentation", "Segmentation")
    expr_name = fields.Selection(
        [("sale", "Sale Amount"), ("purchase", "Purchase Amount")],
        "Control Variable",
        required=True,
        default="sale",
    )
    expr_operator = fields.Selection(
        [("<", "<"), ("=", "="), (">", ">")],
        "Operator",
        required=True,
        default=">",
    )
    expr_value = fields.Float("Value", required=True)
    operator = fields.Selection(
        [("and", "Mandatory Expression"), ("or", "Optional Expression")],
        "Mandatory / Optional",
        required=True,
        default="and",
    )

    def test(self, partner_id):
        """
        :param self:            The current crm.segmentation.line.
        :param partner_id:      The partner object.
        """

        expression = {
            "<": lambda x, y: x < y,
            "=": lambda x, y: x == y,
            ">": lambda x, y: x > y,
        }
        for line in self:
            self.env.cr.execute(
                """
                SELECT * FROM ir_module_module WHERE name=%s AND state=%s
                """,
                ("account", "installed"),
            )

            if self.env.cr.fetchone():
                if line["expr_name"] == "sale":
                    self._cr.execute(
                        """SELECT SUM(l.price_unit * l.quantity)
                        FROM account_move_line l, account_move i
                        WHERE (l.move_id = i.id) AND
                        i.partner_id = %s AND
                        i.move_type = 'out_invoice'
                        """,
                        (partner_id,),
                    )
                    value = self.env.cr.fetchone()[0] or 0.0
                    self.env.cr.execute(
                        """SELECT SUM(l.price_unit * l.quantity)
                        FROM account_move_line l, account_move i
                        WHERE (l.move_id = i.id)
                        AND i.partner_id = %s
                        AND i.move_type = 'out_refund'
                        """,
                        (partner_id,),
                    )
                    value -= self.env.cr.fetchone()[0] or 0.0
                elif line["expr_name"] == "purchase":
                    self.env.cr.execute(
                        """SELECT SUM(l.price_unit * l.quantity)
                        FROM account_move_line l, account_move i
                        WHERE (l.move_id = i.id)
                        AND i.partner_id = %s
                        AND i.move_type = 'in_invoice'
                        """,
                        (partner_id,),
                    )
                    value = self.env.cr.fetchone()[0] or 0.0
                    self.env.cr.execute(
                        """SELECT SUM(l.price_unit * l.quantity)
                        FROM account_move_line l, account_move i
                        WHERE (l.move_id = i.id)
                        AND i.partner_id = %s
                        AND i.move_type = 'in_refund'
                        """,
                        (partner_id,),
                    )
                    value -= self._cr.fetchone()[0] or 0.0
                res = expression[line["expr_operator"]](value, line["expr_value"])

                if not res and (line["operator"] == "and"):
                    return False
                elif res:
                    return True
        return True