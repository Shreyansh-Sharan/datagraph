"""Connections are owned by the Polestar connection module, a separate microservice
(mf-studio-connectors). datagraph never holds adapters or credentials of its own: this package
is only the HTTP client that the API and the Home/Configure screens use to read what the hub
knows. The UI itself renders connection forms with the hub's ``@polestar/connections`` package.
"""
from .hub import HubConnections, HubUnavailable, NoConnectionModule, result_from_report, spec_from_schema

__all__ = ["HubConnections", "HubUnavailable", "NoConnectionModule", "result_from_report", "spec_from_schema"]
