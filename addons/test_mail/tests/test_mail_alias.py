# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import psycopg2

from odoo import exceptions
from odoo.addons.mail.tests.common import MailCommon
from odoo.tests import tagged
from odoo.tests.common import users
from odoo.tools import mute_logger


class TestMailAliasCommon(MailCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._activate_multi_company()

        cls.test_alias_mc = cls.env['mail.alias'].create({
            'alias_model_id': cls.env['ir.model']._get('mail.test.container.mc').id,
            'alias_name': 'test.alias',
        })


@tagged('mail_gateway', 'mail_alias', 'multi_company')
class TestMailAlias(TestMailAliasCommon):
    """ Test alias model features, constraints and behavior. """

    @users('admin')
    def test_alias_domain_allowed_validation(self):
        """ Check the validation of `mail.catchall.domain.allowed` system parameter"""
        for value in [',', ',,', ', ,']:
            with self.assertRaises(exceptions.ValidationError,
                 msg="The value '%s' should not be allowed" % value):
                self.env['ir.config_parameter'].set_param('mail.catchall.domain.allowed', value)

        for value, expected in [
            ('', False),
            ('hello.com', 'hello.com'),
            ('hello.com,,', 'hello.com'),
            ('hello.com,bonjour.com', 'hello.com,bonjour.com'),
            ('hello.COM, BONJOUR.com', 'hello.com,bonjour.com'),
        ]:
            self.env['ir.config_parameter'].set_param('mail.catchall.domain.allowed', value)
            self.assertEqual(self.env['ir.config_parameter'].get_param('mail.catchall.domain.allowed'), expected)

    @users('admin')
    @mute_logger('odoo.models.unlink')
    def test_alias_domain_parameters(self):
        """ Check the validation of ``mail.bounce.alias`` and ``mail.catchall.alias``
        parameters. """
        ICP = self.env['ir.config_parameter']
        # sanitization
        for (bounce_value, catchall_value), (expected_bounce, expected_catchall) in zip(
            [
                ('bounce+b4r=*R3wl_#_-$€{}[]()~|\\/!?&%^\'"`~', 'catchall+b4r=*R3wl_#_-$€{}[]()~|\\/!?&%^\'"`~'),
                ('bounce+😊', 'catchall+😊'),
                ('Bouncâïde 😊', 'Catchôïee 😊'),
                ('ぁ', 'ぁぁ'),
            ],
            [
                ('bounce+b4r-r3wl_-_-', 'catchall+b4r-r3wl_-_-'),
                ('bounce+-', 'catchall+-'),
                ('bouncaide-', 'catchoiee-'),
                ('?', '??'),
            ]
        ):
            with self.subTest(bounce_value=bounce_value):
                ICP.set_param('mail.bounce.alias', bounce_value)
                self.assertEqual(ICP.get_param('mail.bounce.alias'), expected_bounce)
            with self.subTest(catchall_value=catchall_value):
                ICP.set_param('mail.catchall.alias', catchall_value)
                self.assertEqual(ICP.get_param('mail.catchall.alias'), expected_catchall)

        # falsy values FIXME: fix ICP override for '' and ' ' as they make ICP
        # udpate crash, they now try to write False in DB instead of removing
        # the ICP
        for config_value in [False, None]:
            with self.subTest(config_value=config_value):
                ICP.set_param('mail.bounce.alias', config_value)
                self.assertFalse(ICP.get_param('mail.bounce.alias'))
                ICP.set_param('mail.catchall.alias', config_value)
                self.assertFalse(ICP.get_param('mail.catchall.alias'))

        # check successive param set, should not raise for unicity against itself
        for _ in range(2):
            ICP.set_param('mail.bounce.alias', 'bounce+double.test')
            ICP.set_param('mail.catchall.alias', 'catchall+double.test')
            self.assertEqual(ICP.get_param('mail.bounce.alias'), 'bounce+double.test')
            self.assertEqual(ICP.get_param('mail.catchall.alias'), 'catchall+double.test')

    @users('admin')
    def test_alias_name_unique(self):
        alias_model_id = self.env['ir.model']._get('mail.test.gateway').id
        catchall_alias = self.env['ir.config_parameter'].sudo().get_param('mail.catchall.alias')
        bounce_alias = self.env['ir.config_parameter'].sudo().get_param('mail.bounce.alias')

        # test you cannot create aliases matching bounce / catchall
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            self.env['mail.alias'].create({'alias_model_id': alias_model_id, 'alias_name': catchall_alias})
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            self.env['mail.alias'].create({'alias_model_id': alias_model_id, 'alias_name': bounce_alias})

        new_mail_alias = self.env['mail.alias'].create({
            'alias_model_id': alias_model_id,
            'alias_name': 'unused.test.alias'
        })
        other_alias = self.env['mail.alias'].create({
            'alias_model_id': alias_model_id,
            'alias_name': 'other.test.alias'
        })

        # test that alias names should be unique
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            self.env['mail.alias'].create({
                'alias_model_id': alias_model_id,
                'alias_name': 'unused.test.alias',
            })
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            self.env['mail.alias'].create([
                {
                    'alias_model_id': alias_model_id,
                    'alias_name': alias_name,
                }
                for alias_name in ('new.alias.1', 'new.alias.2', 'new.alias.1')
            ])
        with self.assertRaises(psycopg2.errors.UniqueViolation), self.cr.savepoint(), mute_logger('odoo.sql_db'):
            new_mail_alias.copy({'alias_name': 'unused.test.alias'})
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            other_alias.write({'alias_name': 'unused.test.alias'})

        # test that re-using catchall and bounce alias raises UserError
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            new_mail_alias.write({'alias_name': catchall_alias})
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            new_mail_alias.write({'alias_name': bounce_alias})

        new_mail_alias.write({'alias_name': 'another.unused.test.alias'})

        # test that duplicating an alias should have blank name
        copy_1 = new_mail_alias.copy()
        self.assertFalse(copy_1.alias_name)
        # test sanitize of copy with new name
        copy_2 = new_mail_alias.copy({'alias_name': 'test.alias.2.éè#'})
        self.assertEqual(copy_2.alias_name, 'test.alias.2.ee-')

        # cannot batch update, would create duplicates
        with self.assertRaises(exceptions.UserError):
            (copy_1 + copy_2).write({'alias_name': 'test.alias.other'})

        # cannot set catchall / bounce to used alias
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            self.env['ir.config_parameter'].sudo().set_param('mail.catchall.alias', new_mail_alias.alias_name)
        with self.assertRaises(exceptions.UserError), self.cr.savepoint():
            self.env['ir.config_parameter'].sudo().set_param('mail.bounce.alias', new_mail_alias.alias_name)

    @users('admin')
    @mute_logger('odoo.models.unlink')
    def test_alias_name_sanitize(self):
        """ Check sanitizer, at both create, copy and write on alias name. """
        alias_names = [
            'bidule...inc.',
            'b4r+=*R3wl_#_-$€{}[]()~|\\/!?&%^\'"`~',
            'hélène.prôvâïder',
            '😊',
            'Déboulonneur 😊',
            'ぁ',
        ]
        expected_names = [
            'bidule.inc',
            'b4r+-r3wl_-_-',
            'helene.provaider',
            '-',
            'deboulonneur-',
            '?',
        ]
        msgs = [
            'Emails cannot start or end with a dot, there cannot be a sequence of dots.',
            'Disallowed chars should be replaced by hyphens',
            'Email alias should be unaccented',
            'Only a subset of unaccented latin chars are valid, others are replaced',
            'Only a subset of unaccented latin chars are valid, others are replaced',
            'Only a subset of unaccented latin chars are valid, others are replaced',
        ]
        for alias_name, expected, msg in zip(alias_names, expected_names, msgs):
            with self.subTest(alias_name=alias_name):
                alias = self.env['mail.alias'].create({
                    'alias_model_id': self.env['ir.model']._get('mail.test.container').id,
                    'alias_name': alias_name,
                })
                self.assertEqual(alias.alias_name, expected, msg)
                alias.unlink()

        alias = self.env['mail.alias'].create({
            'alias_model_id': self.env['ir.model']._get('mail.test.container').id,
        })
        # check at write
        for alias_name, expected, msg in zip(alias_names, expected_names, msgs):
            with self.subTest(alias_name=alias_name):
                alias.write({'alias_name': alias_name})
                self.assertEqual(alias.alias_name, expected, msg)

    @users('admin')
    def test_alias_name_sanitize_false(self):
        """ Check empty-like aliases are forced to False, as otherwise unique
        constraint might fail with empty strings. """
        aliases = self.env['mail.alias'].create([
            {
                'alias_model_id': self.env['ir.model']._get('mail.test.container').id,
                'alias_name': falsy_name,
            }
            # '.' -> not allowed to start with a "." hence False
            for falsy_name in [False, None, '', ' ', '.']
        ])
        for alias in aliases:
            with self.subTest(alias_name=alias.alias_name):
                self.assertFalse(alias.alias_name, 'Void values should resolve to False')

        # try to reset names in batch: should work
        for idx, alias in enumerate(aliases):
            alias.write({'alias_name': f'unique-{idx}'})
        aliases.write({'alias_name': ''})
        for alias in aliases:
            self.assertEqual(alias.alias_name, False)

    @users('admin')
    def test_alias_setup(self):
        """ Test various constraints / configuration of alias model"""
        alias = self.env['mail.alias'].create({
            'alias_model_id': self.env['ir.model']._get('mail.test.container.mc').id,
            'alias_name': 'unused.test.alias'
        })
        self.assertEqual(alias.alias_status, 'not_tested')

        # validation of alias_defaults
        with self.assertRaises(exceptions.ValidationError):
            alias.write({'alias_defaults': "{'custom_field': brokendict"})
        alias.write({'alias_defaults': "{'custom_field': 'validdict'}"})


@tagged('mail_gateway', 'mail_alias', 'multi_company')
class TestMailAliasMixin(TestMailAliasCommon):
    """ Test alias mixin implementation, synchornization of alias records
    based on owner records. """

    @users('employee')
    @mute_logger('odoo.addons.base.models.ir_model')
    def test_alias_mixin(self):
        record = self.env['mail.test.container'].create({
            'name': 'Test Record',
            'alias_name': 'alias.test',
            'alias_contact': 'followers',
        })
        self.assertEqual(record.alias_id.alias_model_id, self.env['ir.model']._get('mail.test.container'))
        self.assertEqual(record.alias_id.alias_force_thread_id, record.id)
        self.assertEqual(record.alias_id.alias_parent_model_id, self.env['ir.model']._get('mail.test.container'))
        self.assertEqual(record.alias_id.alias_parent_thread_id, record.id)
        self.assertEqual(record.alias_id.alias_name, 'alias.test')
        self.assertEqual(record.alias_id.alias_contact, 'followers')

        record.write({
            'alias_name': 'better.alias.test',
            'alias_defaults': "{'default_name': 'defaults'}"
        })
        self.assertEqual(record.alias_id.alias_name, 'better.alias.test')
        self.assertEqual(record.alias_id.alias_defaults, "{'default_name': 'defaults'}")

        with self.assertRaises(exceptions.AccessError):
            record.write({
                'alias_force_thread_id': 0,
            })

        with self.assertRaises(exceptions.AccessError):
            record.write({
                'alias_model_id': self.env['ir.model']._get('mail.test.gateway').id,
            })

        with self.assertRaises(exceptions.ValidationError):
            record.write({'alias_defaults': "{'custom_field': brokendict"})

    @users('employee')
    def test_alias_mixin_copy_content(self):
        self.assertFalse(self.env.user.has_group('base.group_system'), 'Test user should not have Administrator access')

        record = self.env['mail.test.container'].create({
            'name': 'Test Record',
            'alias_name': 'test.record',
            'alias_contact': 'followers',
            'alias_bounced_content': False,
        })
        self.assertFalse(record.alias_bounced_content)
        record_copy = record.copy()
        self.assertFalse(record_copy.alias_bounced_content)

        new_content = '<p>Bounced Content</p>'
        record_copy.write({'alias_bounced_content': new_content})
        self.assertEqual(record_copy.alias_bounced_content, new_content)
        record_copy2 = record_copy.copy()
        self.assertEqual(record_copy2.alias_bounced_content, new_content)

    @users('erp_manager')
    def test_alias_mixin_mc(self):
        """ Test company change does not impact anything at alias domain level """
        record = self.env['mail.test.container.mc'].create({
            'name': 'Test Record',
            'alias_name': 'alias.test',
            'alias_contact': 'followers',
            'company_id': self.env.user.company_id.id,
        })
        self.assertEqual(record.alias_domain, self.alias_domain)
        self.assertEqual(record.company_id, self.company_2)

        record.write({'company_id': self.company_admin.id})
        self.assertEqual(record.alias_domain, self.alias_domain)
        self.assertEqual(record.company_id, self.company_admin)

        record.write({'company_id': False})
        self.assertEqual(record.alias_domain, self.alias_domain)
        self.assertFalse(record.company_id)
