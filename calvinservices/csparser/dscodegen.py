# -*- coding: utf-8 -*-

# Copyright (c) 2015-2019 Ericsson AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.




from . import astprint
from . import astnode as ast
from .visitor import Visitor, query
from calvinservices.csparser import codegen


class ExpandRules(Visitor):
    """docstring for ExpandRules"""
    def __init__(self, issue_tracker):
        super(ExpandRules, self).__init__()
        self.issue_tracker = issue_tracker

    def process(self, root):
        self.expanded_rules = {}
        rules = query(root, ast.RuleDefinition)
        seen = [rule.name.ident for rule in rules]
        unresolved = rules
        while True:
            self._replaced = False
            for rule in unresolved[:]:
                rule_resolved = self._expand_rule(rule)
                if rule_resolved:
                    self.expanded_rules[rule.name.ident] = rule.rule
                    unresolved.remove(rule)
            if not unresolved:
                # Done
                break
            if not self._replaced:
                # Give up
                for rule in unresolved:
                    reason = "Cannot expand rule '{}'".format(rule.name.ident)
                    self.issue_tracker.add_error(reason, rule)
                return self.expanded_rules
        # OK, final pass over RuleApply
        applies = query(root, ast.RuleApply)
        for a in applies:
            self._expand_rule(a)
        # FIXME: Run a second pass to catch errors

    def _expand_rule(self, rule):
        self._clean = True
        self.visit(rule.rule)
        return self._clean

    def generic_visit(self, node):
        pass

    def visit_SetOp(self, node):
        self.visit(node.left)
        self.visit(node.right)

    def visit_UnarySetOp(self, node):
        self.visit(node.rule)

    def visit_Id(self, node):
        self._clean = False
        if node.ident in self.expanded_rules:
            node.parent.replace_child(node, self.expanded_rules[node.ident].clone())
            self._replaced = True


class DeployInfo(Visitor):
    """docstring for DeployInfo"""
    def __init__(self, root, issue_tracker):
        super(DeployInfo, self).__init__()
        self.root = root
        self.issue_tracker = issue_tracker

    def process(self):
        self.requirements = {}
        self.visit(self.root)


    def visit_RuleApply(self, node):
        rule = self.visit(node.rule)
        for t in node.targets:
            self.requirements[t.ident] = rule

    def visit_RulePredicate(self, node):
        pred = {
            "predicate":node.predicate.ident,
            "kwargs":{arg.ident.ident:arg.arg.value for arg in node.args}
        }
        return pred

    def visit_SetOp(self, node):
        rule = {
            "operator":node.op,
            "operands":[self.visit(node.left), self.visit(node.right)]
        }
        return rule

    def visit_UnarySetOp(self, node):
        rule = {
            "operator":node.op,
            "operand":self.visit(node.rule)
        }
        return rule


class Backport(object):
    """docstring for Backport"""
    def __init__(self, issuetracker):
        super(Backport, self).__init__()
        self.issuetracker = issuetracker

    def transform(self, requirements):
        for actor, rule in requirements.items():
            try:
                new_rule = self.mangle(rule)
                requirements[actor] = new_rule if type(new_rule) is list else [new_rule]
            except Exception as e:
                self.issuetracker.add_error("Cannot mangle rule for actor '{}'".format(actor), info={'line':0, 'col':0})
        return requirements

    def mangle(self, rule):

        def is_predicate(rule):
            return 'predicate' in rule

        def is_intersection(rule):
            return 'operands' in rule and rule['operator'] == '&'

        def is_union(rule):
            return 'operands' in rule and rule['operator'] == '|'

        def is_unary_not(rule):
            return 'operand' in rule and rule['operator'] == '~'

        if is_predicate(rule):
            new_rule = {
                "op": rule["predicate"],
                "kwargs": rule["kwargs"],
                "type": "+"
            }
            return new_rule

        if is_intersection(rule):
            try:
                left = self.mangle(rule['operands'][0])
                right = self.mangle(rule['operands'][1])
                new_rule = (left if type(left) is list else [left]) + (right if type(right) is list else [right])
            except Exception as e:
                print("REASON:", e)
                raise Exception("EXCEPTION (&)\n{}\n{}".format(left, right))
            return new_rule

        if is_union(rule):
            left = self.mangle(rule['operands'][0])
            right = self.mangle(rule['operands'][1])
            ll, rd = False, False
            try:
                if type(left) is dict and 'requirements' in left:
                    left = left['requirements']
                    ll = True
                if type(left) is dict:
                    left.pop('type', None)
                if type(right) is dict and 'requirements' in right:
                    right = right['requirements']
                if type(right) is dict:
                    right.pop('type', None)
                    rd = True
                if  ll and rd:
                    reqs = left + [right]
                else:
                    reqs = [left, right]
                new_rule = {
                    "op": "union_group",
                    "requirements":reqs,
                    "type": "+"
                }
            except Exception as e:
                raise Exception("EXCEPTION (|)\n{}\n{}".format(left, right))
            return new_rule


        if is_unary_not(rule):
            new_rule = {
                "op": rule["operand"]["predicate"],
                "kwargs": rule["operand"]["kwargs"],
                "type": "-"
            }
            return new_rule

        return None


class DSCodeGen(object):

    verbose = False
    verbose_nodes = False

    """
    Generate code from a deploy script file
    """
    def __init__(self, ast_root, script_name):
        super(DSCodeGen, self).__init__()
        self.root = ast_root
        self.dump_tree('ROOT')

    def dump_tree(self, heading):
        if not self.verbose:
            return
        ast.Node._verbose_desc = self.verbose_nodes
        printer = astprint.BracePrinter()
        print("========\n{}\n========".format(heading))
        printer.process(self.root)


    def generate_code_from_ast(self, issue_tracker):
        rc = codegen.ReplaceConstants(issue_tracker)
        rc.process(self.root)
        self.dump_tree('RESOLVED CONSTANTS')


        er = ExpandRules(issue_tracker)
        er.process(self.root)
        self.dump_tree('EXPANDED')

        gen_deploy_info = DeployInfo(self.root, issue_tracker)
        gen_deploy_info.process()

        bp = Backport(issue_tracker)
        return bp.transform(gen_deploy_info.requirements)

    def generate_code(self, issue_tracker):
        requirements = self.generate_code_from_ast(issue_tracker)
        self.deploy_info = {'requirements':requirements}
        self.deploy_info['valid'] = (issue_tracker.error_count == 0)


