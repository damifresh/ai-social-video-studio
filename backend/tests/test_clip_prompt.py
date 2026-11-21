"""Tests for the deterministic Auto-Clip Studio prompter."""

from __future__ import annotations

import unittest

from app.clip import highlights, prompt


class PromptParserTest(unittest.TestCase):
    def test_empty_prompt_has_no_brief(self):
        self.assertEqual(prompt.parse(''), {})
        self.assertEqual(prompt.parse(None), {})

    def test_prompt_extracts_intent_and_weight_rules(self):
        brief = prompt.parse(
            'Funny 15s TikTok clips for beginners about habits; avoid jargon and long intros'
        )
        self.assertEqual(brief['tone'], 'funny')
        self.assertEqual(brief['platform'], 'tiktok')
        self.assertEqual(brief['audience'], 'beginners')
        self.assertIn('habits', brief['keywords'])
        self.assertIn('jargon', brief['avoid'])
        self.assertEqual(brief['length_hint']['seconds'], 15)
        self.assertGreater(brief['weight_multipliers']['hook'], 1.0)
        self.assertTrue(brief['rules'])
        self.assertIn('deterministic', brief['engine'])
        self.assertNotIn('llm_model', brief)


class BriefScoringTest(unittest.TestCase):
    def setUp(self):
        self.transcript = {
            'timing': 'words',
            'sentences': [
                {'start': 0.0, 'end': 5.0, 'text': 'Most people quit habits because the system is too complicated.'},
                {'start': 6.0, 'end': 11.0, 'text': 'The sky appears blue because of scattering in the atmosphere.'},
            ],
        }
        self.structural = {'silence': {'gaps': []}, 'envelope': {}}

    def test_brief_adds_auditable_component_and_prefers_keywords(self):
        brief = prompt.parse('Educational clips about habits')
        result = highlights.generate(
            self.transcript, self.structural, [5], count=2, brief=brief
        )
        self.assertEqual(result['params']['brief'], brief)
        self.assertIn('brief_fit', result['params']['weights'])
        fits = {
            'habits' in c['text']: c['components']['brief_fit']['raw']
            for c in result['candidates']
        }
        self.assertTrue(any('habits' in c['text'] for c in result['candidates']))
        self.assertGreater(fits[True], fits[False])

    def test_tone_can_override_generated_category_when_supported(self):
        transcript = {
            'timing': 'words',
            'sentences': [
                {'start': 0.0, 'end': 5.0, 'text': 'This funny habit changed my morning in a surprisingly simple way.'},
                {'start': 6.0, 'end': 11.0, 'text': 'The meeting starts at nine in the conference room.'},
            ],
        }
        brief = prompt.parse('Funny clips about habits')
        result = highlights.generate(transcript, self.structural, [5], count=2, brief=brief)
        funny = [c for c in result['candidates'] if 'funny' in c['text']]
        self.assertTrue(funny)
        self.assertEqual(funny[0]['category'], 'funny')


if __name__ == '__main__':
    unittest.main()
