from shelftalk.grounding import numbers_in, ungrounded

RESULTS = [{"rows": [["NSW", 26987123.4], ["VIC", 23519870.0], ["TAS", 18.34], ["Milk", 42105]]}]


def test_rounded_numbers_are_grounded():
    text = "NSW led with $26.99M, VIC $23.5 million, TAS share 18.3% and 42,105 units of milk, top 2 in 2025."
    assert ungrounded(text, RESULTS) == []


def test_invented_numbers_are_flagged():
    assert ungrounded("NSW reached $27.4M and TAS 21%.", RESULTS) == ["$27.4M", "21%"]


def test_numbers_from_the_question_are_fine():
    assert ungrounded("Here are the top 15 products.", RESULTS, question="top 15 products") == []


def test_parsing():
    assert [v for _, v, _ in numbers_in("$1.2k, 3 million, -4.5%")] == [1200.0, 3e6, -4.5]
