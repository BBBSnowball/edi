#!/bin/bash -x

# EDI msg / tweet command util
# Author: Marcel Lauhoff <ml@irq0.org>
messenger
# Examles:
# !tweet edi Subraum geoeffnet!
# !msg irc.EDI.send._channel_
# !msg irc.EDI.send._c3pb_
# !msg twitter.sub_edi.send.timeline
# !msg twitter.sub_edi.send.sub_edi dinge
# !msg twitter.sub_edi.action.sub_edi foos around

emit_msg () {
    amqp-publish -u "amqp://${AMQP_SERVER:-localhost}" \
		 -e "msg" \
		 -r "$1" \
		 --content-type="text/plain" \
		 -b "${*:2}"
}

read -a args

case "$EDI_CMD" in
    msg)
	if [[ -n ${args[0]} && -n ${args[@]:1} ]]; then
	    emit_msg "${args[0]}" "${args[@]:1}"
	else
	    echo "USAGE: <msg> <rkey> <message>"
	fi
	;;
    tweet)
	case "${args[0]}" in
	    "edi")
		emit_msg "twitter.sub_edi.send.timeline" "${args[@]:1}"
		;;
	    "c3pb")
		emit_msg "twitter.sub_edi.send.timeline" "${args[@]:1}"
		;;
	    *)
		echo "USAGE: <tweet> <edi|c3pb> <message>"
		;;
	esac
	;;
esac
