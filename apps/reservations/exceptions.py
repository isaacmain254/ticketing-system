class ReservationDomainError(Exception):
    pass


class InvalidReservationQuantity(ReservationDomainError):
    pass


class TicketTypeNotAvailable(ReservationDomainError):
    pass


class InsufficientInventory(ReservationDomainError):
    pass
