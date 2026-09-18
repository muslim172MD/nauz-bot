import unittest

import nauz_bot


class PrivacyGuardTests(unittest.TestCase):
    def test_detects_explicit_patient_identifiers(self):
        samples = [
            "СНИЛС пациента 123-456-789 00",
            "полис ОМС пациента",
            "номер истории болезни 12345",
            "ФИО пациента Иванов Иван Иванович",
            "телефон пациента +7 900 000-00-00",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertTrue(nauz_bot.contains_patient_identifiers(text))

    def test_allows_ordinary_management_context(self):
        text = "В клинике не хватает врачей и нужно улучшить цифровизацию."
        self.assertFalse(nauz_bot.contains_patient_identifiers(text))


if __name__ == "__main__":
    unittest.main()
