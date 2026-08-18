from enum import Enum
from abc import ABC, abstractmethod
import threading
from typing import Dict, List, Optional
from collections import defaultdict
import uuid
import time


class VehicleSize(Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class Vehicle(ABC):
    def __init__(self, size: VehicleSize, license_number: str):
        self._size = size
        self._license_number = license_number

    def get_size(self) -> VehicleSize:
        return self._size

    def get_license_number(self) -> str:
        return self._license_number


class Bike(Vehicle):
    def __init__(self, license_number: str):
        super().__init__(VehicleSize.SMALL, license_number)


class Car(Vehicle):
    def __init__(self, license_number: str):
        super().__init__(VehicleSize.MEDIUM, license_number)


class Truck(Vehicle):
    def __init__(self, license_number: str):
        super().__init__(VehicleSize.LARGE, license_number)


# Rank used for "smallest spot that fits" ordering.
SIZE_RANK = {VehicleSize.SMALL: 0, VehicleSize.MEDIUM: 1, VehicleSize.LARGE: 2}


class ParkingSpot:
    # FIX: spot_id first, size second -- matches how callers naturally write it.
    def __init__(self, spot_id: str, spot_size: VehicleSize):
        self._spot_id = spot_id
        self._spot_size = spot_size
        self._occupied = False
        self._vehicle_parked: Optional[Vehicle] = None
        self._lock = threading.Lock()

    def get_spot_id(self) -> str:
        return self._spot_id

    def get_spot_size(self) -> VehicleSize:
        return self._spot_size

    def is_occupied(self) -> bool:
        with self._lock:
            return self._occupied

    def is_available(self) -> bool:
        return not self.is_occupied()

    def park_vehicle(self, veh: Vehicle) -> bool:
        with self._lock:
            if self._occupied:
                return False
            self._vehicle_parked = veh
            self._occupied = True
            return True

    def unpark_vehicle(self):
        with self._lock:
            self._vehicle_parked = None
            self._occupied = False

    def can_fit_vehicle(self, veh: Vehicle) -> bool:
        with self._lock:
            if self._occupied:
                return False  # FIX: was `return self._occupied` -> True
            return SIZE_RANK[self._spot_size] >= SIZE_RANK[veh.get_size()]


class ParkingFloor:
    def __init__(self, floor_number: int):
        self._floor_number = floor_number
        self._spots: Dict[str, ParkingSpot] = {}
        self._lock = threading.Lock()

    def get_floor_number(self) -> int:
        return self._floor_number

    def add_spot(self, spot: ParkingSpot):
        with self._lock:
            self._spots[spot.get_spot_id()] = spot  # FIX: was spot.get_spotId (no call)

    def find_available_spot(self, veh: Vehicle) -> Optional[ParkingSpot]:
        with self._lock:
            candidates = [s for s in self._spots.values() if s.can_fit_vehicle(veh)]
            if not candidates:
                return None
            # FIX: sort by size rank, not by .value (alphabetical put LARGE first)
            candidates.sort(key=lambda s: (SIZE_RANK[s.get_spot_size()], s.get_spot_id()))
            return candidates[0]

    def display_availability(self):
        print(f"--- Floor {self._floor_number} Availability ---")
        counts = defaultdict(int)
        with self._lock:
            for spot in self._spots.values():
                if not spot.is_occupied():
                    counts[spot.get_spot_size()] += 1  # FIX: was spot.get_spotSize (no call)
        for size in VehicleSize:
            print(f"  {size.value} spots: {counts[size]}")


class ParkingTicket:
    def __init__(self, spot: ParkingSpot, veh: Vehicle):
        self._spot = spot
        self._ticket_number = str(uuid.uuid4())  # FIX: was uuid.uuid4 (no call)
        self._veh = veh
        self._entry_time = int(time.time() * 1000)
        self._exit_time = 0

    def set_exit_time(self):
        self._exit_time = int(time.time() * 1000)

    def get_ticket_number(self) -> str:
        return self._ticket_number

    def get_spot(self) -> ParkingSpot:
        return self._spot

    def get_vehicle(self) -> Vehicle:
        return self._veh

    def get_entry_time(self) -> int:
        return self._entry_time

    def get_exit_time(self) -> int:
        return self._exit_time


class FeeStrategy(ABC):
    @abstractmethod
    def calculate_fee(self, ticket: ParkingTicket) -> float:
        pass


def _billable_hours(ticket: ParkingTicket) -> int:
    duration = ticket.get_exit_time() - ticket.get_entry_time()
    return (duration // (1000 * 60 * 60)) + 1


class VehicleFeeStrategy(FeeStrategy):
    HOURLY = {
        VehicleSize.SMALL: 10.0,
        VehicleSize.MEDIUM: 20.0,
        VehicleSize.LARGE: 30.0,
    }

    def calculate_fee(self, ticket: ParkingTicket) -> float:
        return _billable_hours(ticket) * self.HOURLY[ticket.get_vehicle().get_size()]


class FlatFeeStrategy(FeeStrategy):
    HOURLY = 10.0

    def calculate_fee(self, ticket: ParkingTicket) -> float:
        return _billable_hours(ticket) * self.HOURLY


class ParkingStrategy(ABC):
    @abstractmethod
    def find_spot(self, floors: List[ParkingFloor], veh: Vehicle) -> Optional[ParkingSpot]:
        pass


class NearestFirstStrategy(ParkingStrategy):
    def find_spot(self, floors, veh):
        for floor in floors:
            spot = floor.find_available_spot(veh)
            if spot is not None:
                return spot
        return None


class FarthestFirstStrategy(ParkingStrategy):
    def find_spot(self, floors, veh):
        for floor in reversed(floors):
            spot = floor.find_available_spot(veh)
            if spot is not None:
                return spot
        return None


class BestFitStrategy(ParkingStrategy):
    def find_spot(self, floors, veh):
        best = None
        for floor in floors:
            spot = floor.find_available_spot(veh)
            if spot is None:
                continue
            # FIX: was get_spot_size() on a class that only had get_spotSize()
            if best is None or SIZE_RANK[spot.get_spot_size()] < SIZE_RANK[best.get_spot_size()]:
                best = spot
        return best


class ParkingLot:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        if ParkingLot._instance is not None:
            raise Exception("ParkingLot is a Singleton -- use get_instance()")
        self._floors: List[ParkingFloor] = []
        self._active_tickets: Dict[str, ParkingTicket] = {}
        self._fee_strategy: FeeStrategy = FlatFeeStrategy()
        self._parking_strategy: ParkingStrategy = NearestFirstStrategy()
        self._main_lock = threading.Lock()

    @staticmethod
    def get_instance() -> "ParkingLot":
        if ParkingLot._instance is None:
            with ParkingLot._lock:
                if ParkingLot._instance is None:
                    ParkingLot._instance = ParkingLot()
        return ParkingLot._instance

    def add_floor(self, floor: ParkingFloor):
        with self._main_lock:
            self._floors.append(floor)

    def set_fee_strategy(self, fee_strategy: FeeStrategy):
        self._fee_strategy = fee_strategy

    def set_parking_strategy(self, parking_strategy: ParkingStrategy):
        self._parking_strategy = parking_strategy

    def park_vehicle(self, vehicle: Vehicle) -> Optional[ParkingTicket]:
        with self._main_lock:
            spot = self._parking_strategy.find_spot(self._floors, vehicle)
            if spot is None:
                print(f"No available spot for vehicle {vehicle.get_license_number()}")
                return None
            if not spot.park_vehicle(vehicle):
                print(f"Spot {spot.get_spot_id()} was taken concurrently")
                return None
            ticket = ParkingTicket(spot, vehicle)  # FIX: was (vehicle, spot) -- reversed
            self._active_tickets[vehicle.get_license_number()] = ticket  # FIX: _active_tickets
            print(f"Vehicle {vehicle.get_license_number()} parked at spot {spot.get_spot_id()}")
            return ticket

    def unpark_vehicle(self, license_number: str) -> Optional[float]:
        with self._main_lock:
            ticket = self._active_tickets.pop(license_number, None)
            if ticket is None:
                print(f"Ticket not found for vehicle {license_number}")
                return None
            ticket.get_spot().unpark_vehicle()
            ticket.set_exit_time()          # FIX: was set_exit_timestamp()
            fee = self._fee_strategy.calculate_fee(ticket)   # FIX: was self.fee_strategy
            print(f"Vehicle {license_number} unparked from spot {ticket.get_spot().get_spot_id()}")
            return fee


class ParkingLotDemo:
    @staticmethod
    def main():
        parking_lot = ParkingLot.get_instance()

        floor1 = ParkingFloor(1)
        floor1.add_spot(ParkingSpot("F1-S1", VehicleSize.SMALL))
        floor1.add_spot(ParkingSpot("F1-M1", VehicleSize.MEDIUM))
        floor1.add_spot(ParkingSpot("F1-L1", VehicleSize.LARGE))

        floor2 = ParkingFloor(2)
        floor2.add_spot(ParkingSpot("F2-M1", VehicleSize.MEDIUM))
        floor2.add_spot(ParkingSpot("F2-M2", VehicleSize.MEDIUM))

        parking_lot.add_floor(floor1)
        parking_lot.add_floor(floor2)
        parking_lot.set_fee_strategy(VehicleFeeStrategy())

        print("\n--- Vehicle Entries ---")
        floor1.display_availability()
        floor2.display_availability()

        bike, car, truck = Bike("B-123"), Car("C-456"), Truck("T-789")
        parking_lot.park_vehicle(bike)
        car_ticket = parking_lot.park_vehicle(car)
        parking_lot.park_vehicle(truck)

        print("\n--- Availability after parking ---")
        floor1.display_availability()
        floor2.display_availability()

        parking_lot.park_vehicle(Car("C-999"))   # -> floor 2
        parking_lot.park_vehicle(Bike("B-000"))  # -> no SMALL-or-bigger free spot

        print("\n--- Vehicle Exits ---")
        if car_ticket is not None:
            fee = parking_lot.unpark_vehicle(car.get_license_number())
            if fee is not None:
                print(f"Car C-456 unparked. Fee: ${fee:.2f}")

        print("\n--- Availability after one car leaves ---")
        floor1.display_availability()
        floor2.display_availability()


if __name__ == "__main__":
    ParkingLotDemo.main()