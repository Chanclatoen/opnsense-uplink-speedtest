# Build path for the official framework: drop this directory into
# opnsense/plugins/net/uplink-speedtest and run `make package`.
# install.sh builds the same tree into a package without that checkout.

PLUGIN_NAME=		uplink-speedtest
PLUGIN_VERSION=		1.1.1
PLUGIN_COMMENT=		Periodic uplink speedtest with a dashboard widget
PLUGIN_MAINTAINER=	188175474+Chanclatoen@users.noreply.github.com
PLUGIN_WWW=		https://github.com/Chanclatoen/opnsense-uplink-speedtest
# tracks the Python that OPNsense ships; bump with the base system
PLUGIN_DEPENDS=		py313-speedtest-cli iperf3

.include "../../Mk/plugins.mk"
