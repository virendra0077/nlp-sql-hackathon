def format_result(question, result):

    if len(result) == 1:
        value = result[0][0]
        return f"Answer: {value}"

    return str(result)