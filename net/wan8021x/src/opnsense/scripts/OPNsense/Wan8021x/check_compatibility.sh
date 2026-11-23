#!/bin/sh

supported_series='26.1 26.7'

core_version()
{
	if [ -n "${PKG_ROOTDIR:-}" ] && [ "$PKG_ROOTDIR" != / ]; then
		chroot "$PKG_ROOTDIR" /usr/local/sbin/opnsense-version "$1"
	else
		/usr/local/sbin/opnsense-version "$1"
	fi
}

series=$(core_version -V 2>/dev/null) || series=

case " $supported_series " in
	*" $series "*) exit 0 ;;
esac

version=$(core_version -v 2>/dev/null) || version=
message="os-wan8021x requires OPNsense Community Edition series ${supported_series} (found ${version:-unknown})."
echo "$message" >&2
logger -t wan8021x "$message"
exit 1
