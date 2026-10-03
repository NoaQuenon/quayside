from quayside.render.addressing import allocate
from quayside.render.routing import gateway_routes
from quayside.spec import load_scenario

scn = load_scenario("scenarios/smoke.yaml")
allocs = allocate(scn)
gw_routes = gateway_routes(scn, allocs)

print(allocs)
print(gw_routes)
