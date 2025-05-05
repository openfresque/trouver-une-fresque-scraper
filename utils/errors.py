class FreskError(Exception):
    pass


class FreskDateNotFound(FreskError):
    def __init__(self):
        self.message = f"Date not found."
        super().__init__(self.message)


class FreskDateBadFormat(FreskError):
    def __init__(self, input_str: str):
        self.message = f"Date has a bad format, unhandled by TuF (input: {input_str})."
        super().__init__(self.message)


class FreskDateDifferentTimezone(FreskError):
    def __init__(self, input_str: str):
        self.message = f"Date has a different timezone, unhandled by TuF (input: {input_str})."
        super().__init__(self.message)


class FreskAddressNotFound(FreskError):
    def __init__(self, input_str: str):
        self.message = f"Address not found (input: {input_str})."
        super().__init__(self.message)


class FreskAddressBadFormat(FreskError):
    def __init__(self, address: str, input_str: str, attribute: str):
        self.message = f'Address "{address}" has a bad {attribute} format, unhandled by TuF (input: {input_str}).'
        super().__init__(self.message)


class FreskAddressIncomplete(FreskError):
    def __init__(self, address: str, input_str: str, missing_attribute: str):
        self.message = (
            f'Address "{address}" has a missing attribute {missing_attribute} (input: {input_str}).'
        )
        super().__init__(self.message)


class FreskDepartmentNotFound(FreskError):
    def __init__(self, department: str):
        self.message = f"Department {department} not recognized."
        super().__init__(self.message)


class FreskCountryNotSupported(FreskError):
    def __init__(self, address: str, input_str: str):
        self.message = (
            f'Address "{address}" is not located in a supported country (input: {input_str}).'
        )
        super().__init__(self.message)
