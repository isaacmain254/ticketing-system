class ReservationDomainError(Exception):
    pass


class InvalidReservationQuantity(ReservationDomainError):
    pass


class TicketTypeNotAvailable(ReservationDomainError):
    pass


class InsufficientInventory(ReservationDomainError):
    pass


class ReservationNotFound(ReservationDomainError):
    pass


class ReservationOwnershipDenied(ReservationDomainError):
    pass


class InvalidReservationTransition(ReservationDomainError):
    pass
