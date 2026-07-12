import importlib
import inspect
import pkgutil

import providers
from core.base import DataProvider


def load_providers():
    """自動掃描 providers/ 底下所有模組,回傳每個 DataProvider 子類別的實例。"""
    found = []
    for _, mod_name, _ in pkgutil.iter_modules(providers.__path__):
        mod = importlib.import_module(f"providers.{mod_name}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, DataProvider) and obj is not DataProvider:
                found.append(obj())
    return found
