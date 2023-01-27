import abc
from typing import Dict


class SecretsProvider(abc.ABC):
    TYPE = None

    @abc.abstractmethod
    def get_secret_as_dict(self, secret_id, options={}) -> Dict[str, str]:
        """Retrieve the secret from secrets backend, and return a env var"""
