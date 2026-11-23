PLUGIN_NAME=		wan8021x
PLUGIN_VERSION=		0.2
PLUGIN_DEVEL=		yes
PLUGIN_NO_ABI=		yes
PLUGIN_COMMENT=		IEEE 802.1X wired supplicant for WAN interfaces
PLUGIN_MAINTAINER=	yutong.li@u.nus.edu

.include "../../Mk/plugins.mk"

scripts: scripts-compatibility

# Reuse the installed version check in the pre-install hook, before any files
# from the new package exist. Older OPNsense pkg builds ignore ordinary script
# errors but stop processing the package entirely on exit 3.
scripts-compatibility: scripts-pre
	@{ \
		echo '(' && \
		cat "${.CURDIR}/src/opnsense/scripts/OPNsense/Wan8021x/check_compatibility.sh" && \
		echo ') || exit 3'; \
	} > "${DESTDIR}/+PRE_INSTALL"
