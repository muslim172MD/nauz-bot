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

    def test_detects_common_identifier_formats_without_labels(self):
        samples = [
            "123-456-789 00",
            "1234567890123456",
            "4510 123456",
            "+7 900 123-45-67",
            "patient@example.org",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertTrue(nauz_bot.contains_patient_identifiers(text))

    def test_allows_ordinary_management_context(self):
        samples = [
            "В клинике не хватает врачей и нужно улучшить цифровизацию.",
            "Нужно снизить время ожидания записи на приём.",
            "В организации работает 350 сотрудников.",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertFalse(nauz_bot.contains_patient_identifiers(text))


if __name__ == "__main__":
    unittest.main()
